from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import func, select

from app.db import Artifact, ModelCall, Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.errors import DomainError
from app.llm.budget import BudgetService
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
from app.worker.fencing import fenced_factory
from app.workflow.recovery import recover_run


async def test_plan_interrupt_resumes_with_edit_and_final_checkpoint_reconciles_status():
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "完整工作流", "合成语料检索与综述")
        response = await start_research(
            services, UUID(str(project["id"])), StartResearch(), str(uuid4())
        )
        run_id = UUID(str(response["id"]))
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            lease = await claim_next_run(factory, "test-worker", run_id)
            assert lease
            status = await execute_run(engine, factory, settings, saver, lease)
            assert status == "waiting_user", await get_status(services, run_id)
            planned = await get_plan(services, run_id)
            before = await get_status(services, run_id)
            from app.schemas.contracts import PlanDraft, ResearchPlan

            plan = ResearchPlan.model_validate(planned["plan"])
            draft = PlanDraft.model_validate(
                plan.model_dump(exclude={"plan_id", "project_id", "version", "budgets"})
            )
            draft.scope.exclude_terms = ["unrelated_control"]
            approved = await approve_plan(
                services,
                run_id,
                ApprovePlan(expected_version=plan.version, plan=draft),
                "approve",
            )
            assert approved["active_elapsed_seconds"] == before["active_elapsed_seconds"]
            again = await approve_plan(
                services,
                run_id,
                ApprovePlan(expected_version=plan.version, plan=draft),
                "approve",
            )
            assert again["plan_id"] == approved["plan_id"]
            lease2 = await claim_next_run(factory, "test-worker", run_id)
            assert lease2
            status = await execute_run(engine, factory, settings, saver, lease2)
            assert status == "completed", await get_status(services, run_id)
            async with factory() as session:
                calls_before = await session.scalar(
                    select(func.count()).select_from(ModelCall).where(ModelCall.run_id == run_id)
                )
                count = await session.scalar(
                    select(func.count())
                    .select_from(Artifact)
                    .where(Artifact.run_id == run_id, Artifact.kind == "reading")
                )
                assert count == 2
            # Simulate death after final checkpoint, before the terminal run write.
            async with factory.begin() as session:
                run = await session.get(Run, run_id)
                run.status = "interrupted"
            await recover_run(factory, run_id, None, True)
            resumed = await claim_next_run(factory, "restarted-worker", run_id)
            assert resumed
            assert await execute_run(engine, factory, settings, saver, resumed) == "completed"
            async with factory() as session:
                calls_after = await session.scalar(
                    select(func.count()).select_from(ModelCall).where(ModelCall.run_id == run_id)
                )
                assert calls_before == calls_after
    finally:
        await engine.dispose()


async def test_lost_claim_cannot_flush_business_results():
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "旧执行者", "test")
        run = await start_research(services, UUID(str(project["id"])), StartResearch(), "run")
        run_id = UUID(str(run["id"]))
        lease = await claim_next_run(factory, "old", run_id)
        assert lease
        fenced = fenced_factory(engine, lease)
        async with factory.begin() as session:
            stored = await session.get(Run, run_id)
            stored.claim_token = uuid4()
        with pytest.raises(DomainError) as lost:
            async with fenced.begin() as session:
                session.add(
                    Artifact(
                        run_id=run_id,
                        operation_key="old",
                        kind="review",
                        input_hash="x",
                        payload_json={},
                    )
                )
        assert lost.value.code == "CLAIM_LOST"
        with pytest.raises(DomainError) as unconfirmed:
            await recover_run(factory, run_id, lease.claim_token, False)
        assert unconfirmed.value.code == "WORKER_STOP_NOT_CONFIRMED"
    finally:
        await engine.dispose()


async def test_unknown_call_is_not_automatically_retried():
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "未知调用", "test")
        result = await start_research(services, UUID(str(project["id"])), StartResearch(), "run")
        run_id = UUID(str(result["id"]))
        budget = BudgetService(factory)
        reserved = await budget.reserve_call(run_id, "uncertain", "hash", 1000)
        await budget.mark_sent(reserved.call_id)
        await budget.mark_unknown(reserved.call_id)
        lease = await claim_next_run(factory, "test", run_id)
        assert lease
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            assert await execute_run(engine, factory, settings, saver, lease) == "interrupted"
        status = await get_status(services, run_id)
        assert status["used_calls"] == 1 and status["reserved_tokens"] == 1000
        await recover_run(factory, run_id, None, True)
        status = await get_status(services, run_id)
        assert status["status"] == "interrupted" and status["unknown_calls"] == 1
    finally:
        await engine.dispose()
