from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.db import Run
from app.db.session import create_engine, get_test_settings, session_factory
from app.mcp_gateway.server import build_mcp_server
from app.services.base import Services
from app.services.projects import create_project
from app.services.research import StartResearch, start_research
from app.worker.claim import claim_next_run
from app.worker.execute import execute_run


async def test_status_returns_round_fields_before_the_loop_finishes():
    settings = get_test_settings().model_copy(
        update={"planner_mode": "coverage", "max_research_rounds": 2, "mcp_enabled": False}
    )
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "状态不等待", "图神经网络文献")
        project_id = UUID(str(project["id"]))
        started = await start_research(services, project_id, StartResearch(), "status-live")
        run_id = UUID(str(started["id"]))
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            lease = await claim_next_run(factory, "status-live", run_id)
            assert lease
            assert await execute_run(engine, factory, settings, saver, lease) == "waiting_user"
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
        assert '"round_index"' in text
        assert '"unmet_question_ids"' in text
        assert '"stop_reason"' in text
        async with factory() as session:
            stored = await session.get(Run, run_id)
        assert stored is not None
        assert stored.status == "waiting_user"
    finally:
        await engine.dispose()
