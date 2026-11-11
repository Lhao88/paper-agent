import json
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import ResearchPlan as PlanRow
from app.db import Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.errors import DomainError
from app.repositories.projects import ProjectRepository
from app.schemas.contracts import ResearchPlan, ResearchSpec
from app.services.base import Services
from app.services.projects import create_project
from app.services.research import (
    ApprovePlan,
    StartResearch,
    approve_plan,
    get_plan,
    start_research,
)
from app.worker.claim import claim_next_run
from app.worker.execute import execute_run


def test_settings_without_env_file_stay_on_legacy_planner() -> None:
    assert Settings(_env_file=None).planner_mode == "legacy"


async def test_legacy_plan_row_without_spec_json_remains_readable(db_session: AsyncSession) -> None:
    project = await ProjectRepository(db_session).create("旧计划", "图神经网络")
    questions = [
        {
            "question_id": f"q{index}",
            "text_zh": f"问题{index}",
            "search_terms_en": ["graph"],
            "priority": 2,
        }
        for index in range(1, 4)
    ]
    scope = {
        "year_from": 2020,
        "year_to": None,
        "languages": ["en"],
        "include_terms": [],
        "exclude_terms": [],
        "enabled_sources": ["openalex"],
    }
    row = PlanRow(
        project_id=project.id,
        version=1,
        questions_json=questions,
        scope_json=scope,
    )
    db_session.add(row)
    await db_session.flush()
    loaded = await db_session.get(PlanRow, row.id)
    assert loaded is not None
    assert loaded.spec_json is None
    plan = ResearchPlan(
        topic=project.topic,
        questions=loaded.questions_json,
        scope=loaded.scope_json,
        plan_id=loaded.id,
        project_id=loaded.project_id,
        version=loaded.version,
    )
    assert [question.question_id for question in plan.questions] == ["q1", "q2", "q3"]


async def test_new_run_snapshot_freezes_legacy_planner_without_secrets() -> None:
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    try:
        services = Services(settings, factory)
        project = await create_project(services, "规格快照", "图神经网络")
        accepted = await start_research(
            services, UUID(str(project["id"])), StartResearch(), "spec-snapshot"
        )
    finally:
        await engine.dispose()
    snapshot = accepted["config_snapshot"]
    assert isinstance(snapshot, dict)
    assert snapshot["planner_mode"] == "legacy"
    assert snapshot["embedding_mode"] == "mock"
    assert snapshot["enable_semantic_scholar"] is False
    assert "semantic_scholar_api_key" not in snapshot
    assert "llm_api_key" not in snapshot
    assert "api_key" not in json.dumps(snapshot)


async def test_stale_plan_version_is_rejected_and_legacy_plan_stays_readable() -> None:
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "过期确认", "图神经网络")
        started = await start_research(
            services, UUID(str(project["id"])), StartResearch(), str(uuid4())
        )
        run_id = UUID(str(started["id"]))
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            lease = await claim_next_run(factory, "spec-storage", run_id)
            assert lease
            assert await execute_run(engine, factory, settings, saver, lease) == "waiting_user"
            planned = await get_plan(services, run_id)
            plan = ResearchPlan.model_validate(planned["plan"])
            assert planned["spec"] is None
            with pytest.raises(DomainError) as conflict:
                await approve_plan(
                    services,
                    run_id,
                    ApprovePlan(expected_version=plan.version + 1),
                    "stale-plan",
                )
            assert conflict.value.code == "VERSION_CONFLICT"
            again = await get_plan(services, run_id)
            assert ResearchPlan.model_validate(again["plan"]).version == plan.version
            assert again["spec"] is None
    finally:
        await engine.dispose()


async def test_approve_spec_writes_the_same_freeze_into_both_snapshots() -> None:
    settings = get_test_settings().model_copy(
        update={"planner_mode": "coverage", "max_research_rounds": 2}
    )
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "双快照", "图神经网络文献")
        started = await start_research(
            services, UUID(str(project["id"])), StartResearch(), str(uuid4())
        )
        run_id = UUID(str(started["id"]))
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            lease = await claim_next_run(factory, "freeze-worker", run_id)
            assert lease
            assert await execute_run(engine, factory, settings, saver, lease) == "waiting_user"
            planned = await get_plan(services, run_id)
            plan = ResearchPlan.model_validate(planned["plan"])
            spec = ResearchSpec.model_validate(planned["spec"])
            assert spec.inclusion_rules and spec.columns and spec.coverage
            await approve_plan(
                services,
                run_id,
                ApprovePlan(expected_version=plan.version),
                "freeze-approve",
            )
            resumed = await claim_next_run(factory, "freeze-worker", run_id)
            assert resumed
            assert await execute_run(engine, factory, settings, saver, resumed) == "completed"
        async with factory() as session:
            stored = await session.get(Run, run_id)
            assert stored is not None
            keys = {
                "planner_mode",
                "max_research_rounds",
                "max_actions_per_round",
                "max_citation_neighbors",
                "max_search_in_paper_calls_per_paper",
                "embedding_mode",
                "enabled_sources",
                "max_source_requests",
                "max_llm_calls",
                "max_deep_read_papers",
            }
            for key in keys:
                assert stored.input_snapshot[key] == stored.config_snapshot[key]
            assert stored.input_snapshot["planner_mode"] == "coverage"
            assert stored.config_snapshot["max_research_rounds"] == 2
    finally:
        await engine.dispose()
