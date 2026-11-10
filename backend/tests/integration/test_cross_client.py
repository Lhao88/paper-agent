from uuid import UUID

from sqlalchemy import select

from app.agents.context import AgentContext, RepositoryAccess
from app.config import PROJECT_ROOT
from app.db import Run, Task
from app.db.session import create_engine, get_test_settings, session_factory
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.mcp_gateway.server import build_mcp_server
from app.schemas.contracts import PlanDraft, ResearchPlan
from app.services.base import Services
from app.services.literature import SearchRequest, submit_search
from app.services.projects import create_project
from app.services.research import StartResearch, start_research
from app.sources.mock import MockPaperSource
from app.worker.claim import claim_next_run
from app.workflow.literature import drain_search_tasks


async def test_mcp_and_internal_search_share_idempotency_and_one_source_budget():
    settings = get_test_settings().model_copy(update={"max_source_requests": 1})
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "跨入口检索测试", "synthetic")
        accepted = await start_research(services, UUID(str(project["id"])), StartResearch(), "run")
        run_id = UUID(str(accepted["id"]))
        lease = await claim_next_run(factory, "test", run_id)
        assert lease
        from app.db import Artifact
        from app.db import ResearchPlan as PlanRow

        draft = PlanDraft.model_validate_json(
            (PROJECT_ROOT / "backend/fixtures/model/PlanDraft.json").read_text(encoding="utf-8")
        )
        async with factory.begin() as session:
            row = PlanRow(
                project_id=UUID(str(project["id"])),
                version=1,
                questions_json=[q.model_dump(mode="json") for q in draft.questions],
                scope_json=draft.scope.model_dump(mode="json"),
            )
            session.add(row)
            await session.flush()
            plan = ResearchPlan(
                **draft.model_dump(), plan_id=row.id, project_id=row.project_id, version=1
            )
            session.add(
                Artifact(
                    run_id=run_id,
                    kind="plan",
                    operation_key=f"plan:{row.id}",
                    input_hash="fixture",
                    payload_json=plan.model_dump(mode="json"),
                )
            )
            run = await session.get(Run, run_id)
            run.plan_id, run.stage, run.retrieval_accepting = row.id, "retrieve", True
        server = build_mcp_server(services, settings)
        arguments = {
            "project_id": project["id"],
            "run_id": str(run_id),
            "query": "retrieval",
            "question_ids": ["q1"],
            "idempotency_key": "same-search",
            "limit": 1,
        }
        response = await server.call_tool("search_papers", arguments)
        task_id = response.structured_content["data"]["task_id"]
        internal = await submit_search(
            services,
            plan.project_id,
            run_id,
            SearchRequest(query="retrieval", question_ids=["q1"], limit=1),
            "same-search",
        )
        assert internal["id"] == task_id
        budget = BudgetService(factory)
        context = AgentContext(
            run_id,
            plan.plan_id,
            ModelGateway(
                budget, MockModelTransport(PROJECT_ROOT / "backend/fixtures/model"), settings
            ),
            budget,
            settings,
            RepositoryAccess(factory),
        )
        await drain_search_tasks(
            context,
            factory,
            lease,
            plan,
            {"openalex": MockPaperSource(PROJECT_ROOT / "backend/fixtures/papers.json")},
        )
        async with factory() as session:
            stored = await session.get(Task, UUID(task_id))
            run = await session.get(Run, run_id)
            assert stored.status == "completed" and stored.output_json["count"] == 1
            assert run.used_source_requests == 1 and not run.retrieval_accepting
            count = list(
                await session.scalars(
                    select(Task.id).where(
                        Task.client_request_key == "same-search", Task.run_id == run_id
                    )
                )
            )
            assert len(count) == 1
    finally:
        await engine.dispose()
