from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Run, RunEvent
from app.errors import DomainError


@dataclass(frozen=True)
class RunLease:
    run_id: UUID
    worker_id: str
    claim_token: UUID


async def lock_owned(session: AsyncSession, lease: RunLease) -> Run:
    run = await session.scalar(select(Run).where(Run.id == lease.run_id).with_for_update())
    if (
        run is None
        or run.claim_token != lease.claim_token
        or run.worker_id != lease.worker_id
        or run.status != "running"
    ):
        raise DomainError("CLAIM_LOST", "运行归属已改变，停止提交结果。")
    return run


async def claim_next_run(
    factory: async_sessionmaker[AsyncSession], worker_id: str, run_id: UUID | None = None
) -> RunLease | None:
    async with factory.begin() as session:
        query = select(Run).where(Run.status == "queued", Run.available_at <= datetime.now(UTC))
        if run_id:
            query = query.where(Run.id == run_id)
        run = await session.scalar(
            query.order_by(Run.created_at, Run.id).limit(1).with_for_update(skip_locked=True)
        )
        if run is None:
            return None
        now = datetime.now(UTC)
        run.status, run.worker_id, run.claim_token = "running", worker_id, uuid4()
        run.started_at = run.started_at or now
        run.heartbeat_at, run.lease_until = now, now + timedelta(seconds=60)
        session.add(
            RunEvent(run_id=run.id, event_type="claimed", payload_json={"worker_id": worker_id})
        )
        return RunLease(run.id, worker_id, run.claim_token)


async def heartbeat(
    factory: async_sessionmaker[AsyncSession], lease: RunLease, elapsed: float
) -> bool:
    async with factory.begin() as session:
        run = await lock_owned(session, lease)
        now = datetime.now(UTC)
        run.heartbeat_at, run.lease_until = now, now + timedelta(seconds=60)
        run.active_elapsed_seconds += max(elapsed, 0)
        return run.cancel_requested_at is not None


async def release_run(
    factory: async_sessionmaker[AsyncSession],
    lease: RunLease,
    status: str,
    error: dict[str, object] | None,
    elapsed: float = 0,
) -> None:
    async with factory.begin() as session:
        run = await lock_owned(session, lease)
        run.status, run.error_json = status, error
        run.active_elapsed_seconds += max(elapsed, 0)
        run.worker_id = run.claim_token = run.lease_until = None
        run.retrieval_accepting = False
        if status not in {"waiting_user", "interrupted"}:
            run.finished_at = datetime.now(UTC)
        session.add(
            RunEvent(
                run_id=run.id, event_type="status", payload_json={"status": status, "error": error}
            )
        )
