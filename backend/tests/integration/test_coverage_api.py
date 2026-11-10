from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.db import Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.errors import DomainError
from app.main import create_app
from app.mcp_gateway.server import build_mcp_server
from app.runtime import create_event_loop
from app.schemas.contracts import InclusionRule, ResearchPlan, ResearchSpec
from app.services.base import Services
from app.services.projects import create_project
from app.services.research import (
    ApprovePlan,
    StartResearch,
    approve_plan,
    get_notebook,
    get_plan,
    get_status,
    start_research,
)
from app.worker.claim import claim_next_run
from app.worker.execute import execute_run


async def test_spec_edit_bumps_version_and_status_exposes_coverage():
    settings = get_test_settings().model_copy(
        update={"planner_mode": "coverage", "max_research_rounds": 2, "mcp_enabled": False}
    )
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "规格确认", "图神经网络文献")
        project_id = UUID(str(project["id"]))
        started = await start_research(services, project_id, StartResearch(), "coverage-api")
        run_id = UUID(str(started["id"]))
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            lease = await claim_next_run(factory, "coverage-api", run_id)
            assert lease
            assert await execute_run(engine, factory, settings, saver, lease) == "waiting_user"
            planned = await get_plan(services, run_id)
            plan = ResearchPlan.model_validate(planned["plan"])
            spec = ResearchSpec.model_validate(planned["spec"])
            edited = spec.model_copy(
                update={
                    "inclusion_rules": [
                        *spec.inclusion_rules,
                        InclusionRule(
                            rule_id="r-extra",
                            polarity="exclude",
                            text_zh="排除与图神经网络无关的论文",
                        ),
                    ]
                }
            )
            await approve_plan(
                services,
                run_id,
                ApprovePlan(expected_version=plan.version, spec=edited),
                "edit-spec",
            )
            confirmed = await get_plan(services, run_id)
            assert ResearchPlan.model_validate(confirmed["plan"]).version == plan.version + 1
            stored = ResearchSpec.model_validate(confirmed["spec"])
            assert stored.inclusion_rules[-1].rule_id == "r-extra"
            async with factory.begin() as session:
                run = await session.get(Run, run_id)
                run.status, run.stage = "waiting_user", "approve_plan"
            with pytest.raises(DomainError) as conflict:
                await approve_plan(
                    services,
                    run_id,
                    ApprovePlan(expected_version=plan.version, spec=edited),
                    "stale-spec",
                )
            assert conflict.value.code == "VERSION_CONFLICT"
            app = create_app(settings)
            with TestClient(app, backend_options={"loop_factory": create_event_loop}) as client:
                response = client.post(
                    f"/api/runs/{run_id}/approve",
                    headers={"Idempotency-Key": "stale-http"},
                    json={"expected_version": plan.version, "spec": edited.model_dump(mode="json")},
                )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "VERSION_CONFLICT"
            async with factory.begin() as session:
                run = await session.get(Run, run_id)
                run.status = "queued"
            resumed = await claim_next_run(factory, "coverage-api", run_id)
            assert resumed
            assert await execute_run(engine, factory, settings, saver, resumed) == "completed"
        status = await get_status(services, run_id)
        assert status["round_index"] == 2
        assert "q2" in status["unmet_question_ids"]
        assert isinstance(status["stop_reason"], str)
        notebook = await get_notebook(services, run_id)
        assert [page["round_index"] for page in notebook["pages"]] == [0, 1]
        assert notebook["unmet_question_ids"] == status["unmet_question_ids"]
        server = build_mcp_server(services, settings)
        listed = await server.list_tools()
        assert {tool.name for tool in listed} == {
            "list_projects",
            "start_research",
            "get_research_status",
            "approve_research_plan",
            "cancel_research",
            "search_papers",
            "get_paper_details",
            "get_review",
            "get_evidence",
        }
        result = await server.call_tool(
            "get_research_status", {"project_id": str(project_id), "run_id": str(run_id)}
        )
        text = result.content[0].text
        assert '"round_index": 2' in text or '"round_index":2' in text
        assert "unmet_question_ids" in text
    finally:
        await engine.dispose()
