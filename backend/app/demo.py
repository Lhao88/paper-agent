from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.config import Settings
from app.db import Project
from app.db.session import create_engine, session_factory
from app.demo_fixtures import ensure_extended_fixtures
from app.services.base import Services
from app.services.projects import create_project
from app.services.research import (
    ApprovePlan,
    StartResearch,
    approve_plan,
    get_plan,
    get_status,
    start_research,
)
from app.worker.claim import claim_next_run
from app.worker.execute import execute_run


async def demo_seed(settings: Settings) -> dict[str, object]:
    ensure_extended_fixtures()
    engine = create_engine(settings)
    try:
        services = Services(settings, session_factory(engine))
        async with services.factory() as session:
            existing = await session.scalar(
                select(Project)
                .where(Project.title == "[演示 extended-v1] 学术研究工作台")
                .order_by(Project.created_at)
                .limit(1)
            )
        if existing:
            return {"project_id": str(existing.id), "synthetic": True, "reused": True}
        project = await create_project(
            services, "[演示 extended-v1] 学术研究工作台", "原创合成资料：检索、证据与文献综述"
        )
        return {"project_id": project["id"], "synthetic": True, "reused": False}
    finally:
        await engine.dispose()


async def run_demo(settings: Settings, approve_fixture: bool) -> dict[str, object]:
    frozen = settings.model_copy(
        update={"llm_mode": "mock", "source_mode": "mock", "mock_corpus_profile": "extended"}
    )
    project = await demo_seed(frozen)
    engine = create_engine(frozen)
    factory = session_factory(engine)
    services = Services(frozen, factory)
    try:
        created = await start_research(
            services, UUID(str(project["project_id"])), StartResearch(), "demo-extended-v1"
        )
        run_id = UUID(str(created["id"]))
        async with AsyncPostgresSaver.from_conn_string(frozen.checkpoint_dsn) as saver:
            await saver.setup()
            lease = await claim_next_run(factory, "demo-cli", run_id)
            if lease:
                await execute_run(engine, factory, frozen, saver, lease)
            current = await get_status(services, run_id)
            if approve_fixture and current["status"] == "waiting_user":
                plan = await get_plan(services, run_id)
                from app.schemas.contracts import ResearchPlan

                typed = ResearchPlan.model_validate(plan["plan"])
                await approve_plan(
                    services, run_id, ApprovePlan(expected_version=typed.version), "demo-approve-v1"
                )
                lease = await claim_next_run(factory, "demo-cli", run_id)
                if lease:
                    await execute_run(engine, factory, frozen, saver, lease)
            status = await get_status(services, run_id)
            return {
                "project_id": project["project_id"],
                "run_id": str(run_id),
                "status": status["status"],
                "synthetic": True,
                "error": status["error_json"],
                "counts": status["counts"],
            }
    finally:
        await engine.dispose()
