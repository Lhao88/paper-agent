from uuid import UUID, uuid4

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.db.session import create_engine, get_test_settings, session_factory
from app.main import create_app
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
from app.workflow.nodes import WorkflowNodes
from app.workflow.recovery import recover_run


async def test_saved_reading_is_reused_after_later_node_crash_and_api_versions(monkeypatch):
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    app = create_app(settings)
    try:
        project = await create_project(services, "故障注入", "synthetic")
        result = await start_research(
            services, UUID(str(project["id"])), StartResearch(), str(uuid4())
        )
        run_id = UUID(str(result["id"]))
        original = WorkflowNodes.analyze

        async def crash(*args):
            raise RuntimeError("injected after persisted reading")

        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            lease = await claim_next_run(factory, "failure-worker", run_id)
            assert lease
            assert await execute_run(engine, factory, settings, saver, lease) == "waiting_user"
            plan = await get_plan(services, run_id)
            await approve_plan(
                services, run_id, ApprovePlan(expected_version=plan["plan"]["version"]), "approve"
            )
            monkeypatch.setattr(WorkflowNodes, "analyze", crash)
            lease = await claim_next_run(factory, "failure-worker", run_id)
            assert await execute_run(engine, factory, settings, saver, lease) == "failed"
            stopped = await get_status(services, run_id)
            assert stopped["counts"]["reading"] == 2
            calls_before = stopped["used_calls"]
            monkeypatch.setattr(WorkflowNodes, "analyze", original)
            await recover_run(factory, run_id, None, True)
            lease = await claim_next_run(factory, "restarted", run_id)
            assert await execute_run(engine, factory, settings, saver, lease) == "completed"
            after = await get_status(services, run_id)
            assert after["counts"]["reading"] == 2
            assert (
                after["used_calls"] - calls_before == 7
            )  # analyze, decision, four sections, one check
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                project_id = str(project["id"])
                reviews = (await client.get(f"/api/projects/{project_id}/reviews")).json()
                identifier = reviews[0]["id"]
                view = (await client.get(f"/api/projects/{project_id}/reviews/{identifier}")).json()
                evidence = view["review"]["evidence"][0]["evidence_id"]
                response = await client.get(f"/api/projects/{project_id}/evidence/{evidence}")
                assert response.status_code == 200 and response.json()["evidence_id"] == evidence
                foreign = await create_project(services, "其他项目", "test")
                assert (
                    await client.get(f"/api/projects/{foreign['id']}/evidence/{evidence}")
                ).status_code == 404
                block = view["review"]["sections"][0]["blocks"][0]["block_id"]
                body = {
                    "base_version": view["version"],
                    "edited_blocks": {block: "用户修订内容，待核验。"},
                }
                first = await client.post(
                    f"/api/projects/{project_id}/reviews/{identifier}/edits", json=body
                )
                assert first.status_code == 201
                assert (
                    await client.post(
                        f"/api/projects/{project_id}/reviews/{identifier}/edits", json=body
                    )
                ).status_code == 409
                unchanged = (
                    await client.get(f"/api/projects/{project_id}/reviews/{identifier}")
                ).json()
                assert (
                    unchanged["review"]["sections"][0]["blocks"][0]["text"]
                    != body["edited_blocks"][block]
                )
    finally:
        await engine.dispose()
