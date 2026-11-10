import asyncio
from contextlib import suppress
from uuid import uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from app.config import get_settings
from app.db.session import create_engine, session_factory
from app.errors import DomainError
from app.runtime import run_async
from app.worker.claim import claim_next_run
from app.worker.execute import execute_run

WORKER_LOCK = 734625198


async def serve() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    worker_id = f"local-{uuid4()}"
    try:
        # A dedicated session-level advisory lock, never a pooled business transaction.
        async with engine.connect() as singleton:
            acquired = await singleton.scalar(
                text("select pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK}
            )
            if not acquired:
                raise DomainError("WORKER_ALREADY_RUNNING", "已有worker持有调度锁。")
            try:
                async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
                    while True:
                        await singleton.execute(text("select 1"))
                        lease = await claim_next_run(factory, worker_id)
                        if lease:
                            execution = asyncio.create_task(
                                execute_run(engine, factory, settings, saver, lease)
                            )
                            try:
                                while not execution.done():
                                    await asyncio.wait({execution}, timeout=1)
                                    await singleton.execute(text("select 1"))
                                status = await execution
                            except BaseException:
                                execution.cancel()
                                with suppress(asyncio.CancelledError, Exception):
                                    await execution
                                raise
                            print(f"Run {lease.run_id}: {status}")
                        else:
                            await asyncio.sleep(1)
            finally:
                await singleton.execute(
                    text("select pg_advisory_unlock(:key)"), {"key": WORKER_LOCK}
                )
    finally:
        await engine.dispose()


def main() -> None:
    try:
        run_async(serve())
    except KeyboardInterrupt:
        pass
    except DomainError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from None


if __name__ == "__main__":
    main()
