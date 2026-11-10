"""Test-only API and scoped worker. Never uses the business database or live models."""

import asyncio
import os
from contextlib import suppress

import uvicorn
from alembic import command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.cli import init_checkpoints, migration_config
from app.config import Settings
from app.db import Project, Run
from app.db.session import assert_test_database, create_engine, get_test_settings, session_factory
from app.main import create_app
from app.runtime import run_async
from app.worker.claim import claim_next_run
from app.worker.execute import execute_run


async def serve(settings: Settings, prefix: str, port: int) -> None:
    engine = create_engine(settings)
    factory = session_factory(engine)
    async with factory() as session:
        await assert_test_database(session)
    await init_checkpoints(settings)
    stop = asyncio.Event()

    async def worker() -> None:
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            while not stop.is_set():
                async with factory() as session:
                    identifier = await session.scalar(
                        select(Run.id)
                        .join(Project, Project.id == Run.project_id)
                        .where(
                            Run.status == "queued",
                            Project.title.startswith(prefix, autoescape=True),
                        )
                        .order_by(Run.created_at)
                        .limit(1)
                    )
                lease = (
                    await claim_next_run(factory, "e2e-scoped-worker", identifier)
                    if identifier
                    else None
                )
                if lease:
                    await execute_run(engine, factory, settings, saver, lease)
                else:
                    await asyncio.sleep(0.1)

    background = asyncio.create_task(worker())
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    try:
        await server.serve()
    finally:
        stop.set()
        background.cancel()
        with suppress(asyncio.CancelledError):
            await background
        await engine.dispose()


def main() -> None:
    prefix = os.environ.get("E2E_PROJECT_PREFIX", "")
    if not prefix.startswith("[e2e-"):
        raise SystemExit("E2E_PROJECT_PREFIX must identify an isolated test run.")
    original = get_test_settings()
    settings = original.model_copy(
        update={
            "llm_mode": "mock",
            "source_mode": "mock",
            "planner_mode": "coverage",
            "max_research_rounds": 2,
            "mcp_enabled": True,
            "storage_root": original.storage_root / "e2e",
        }
    )
    command.upgrade(migration_config(settings), "head")
    run_async(serve(settings, prefix, int(os.environ.get("E2E_API_PORT", "18010"))))


if __name__ == "__main__":
    main()
