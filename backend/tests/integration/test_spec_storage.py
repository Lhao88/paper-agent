import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import ResearchPlan as PlanRow
from app.db.session import create_engine, get_test_settings, session_factory
from app.repositories.projects import ProjectRepository
from app.schemas.contracts import ResearchPlan
from app.services.base import Services
from app.services.projects import create_project
from app.services.research import StartResearch, start_research


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
