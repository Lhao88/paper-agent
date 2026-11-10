from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import ORMExecuteState, Session

from app.db import Run
from app.errors import DomainError
from app.worker.claim import RunLease


def fenced_factory(engine: AsyncEngine, lease: RunLease) -> async_sessionmaker[AsyncSession]:
    """Guard every ORM flush and bulk DML in short business transactions.

    The synchronous hooks run inside SQLAlchemy's async greenlet, so the row lock
    uses the same transaction as the result write. Checkpoint writes are separate;
    this guard intentionally does not claim to fence LangGraph's saver.
    """

    class OwnedSession(Session):
        pass

    def check(session: Session) -> None:
        with session.no_autoflush:
            row = session.execute(
                select(Run.__table__.c.claim_token, Run.__table__.c.status)
                .where(Run.__table__.c.id == lease.run_id)
                .with_for_update()
            ).first()
        if row is None or row.claim_token != lease.claim_token or row.status != "running":
            raise DomainError("CLAIM_LOST", "旧执行者不得写入新的业务结果。")

    @event.listens_for(OwnedSession, "before_flush")
    def before_flush(session: Session, flush_context: object, instances: object) -> None:
        check(session)

    @event.listens_for(OwnedSession, "do_orm_execute")
    def before_dml(state: ORMExecuteState) -> None:
        if state.is_insert or state.is_update or state.is_delete:
            check(state.session)

    return async_sessionmaker(engine, expire_on_commit=False, sync_session_class=OwnedSession)
