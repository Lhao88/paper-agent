from uuid import UUID, uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import func, select

from app.agents.context import AgentContext, RepositoryAccess
from app.config import PROJECT_ROOT
from app.db import Artifact, Claim, ModelCall, PaperSource, ProjectPaper, Run, Task
from app.db.session import create_engine, get_test_settings, session_factory
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.review.models import ReviewBundle
from app.schemas.contracts import (
    CoverageReport,
    NotebookPage,
    ResearchPlan,
    ResearchSpec,
    RetrievalResult,
)
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
from app.worker.claim import RunLease, claim_next_run
from app.worker.execute import execute_run
from app.worker.fencing import fenced_factory
from app.workflow.coverage_flow import execute as execute_round
from app.workflow.coverage_flow import propose
from app.workflow.nodes import WorkflowNodes
from app.workflow.state import initial_state


async def test_coverage_loop_replans_records_claims_and_skips_replay():
    settings = get_test_settings().model_copy(
        update={"planner_mode": "coverage", "max_research_rounds": 2}
    )
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "覆盖循环", "图神经网络文献")
        project_id = UUID(str(project["id"]))
        response = await start_research(services, project_id, StartResearch(), "coverage-run")
        run_id = UUID(str(response["id"]))
        async with factory() as session:
            stored = await session.get(Run, run_id)
            assert stored is not None
            assert stored.config_snapshot["planner_mode"] == "coverage"
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            await _complete(engine, factory, settings, services, saver, run_id)
        async with factory() as session:
            tasks = list(
                await session.scalars(
                    select(Task)
                    .where(Task.run_id == run_id, Task.operation == "source_search")
                    .order_by(Task.created_at, Task.id)
                )
            )
            notes = [
                NotebookPage.model_validate(artifact.payload_json)
                for artifact in await session.scalars(
                    select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == "notebook")
                )
            ]
            coverage = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run_id,
                    Artifact.operation_key == f"coverage:{run_id}:1",
                )
            )
            review = await session.scalar(
                select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == "review_bundle")
            )
            plan_row = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run_id, Artifact.operation_key.startswith("plan:")
                )
            )
        assert [task.input_json["query"]["terms"] for task in tasks] == [
            "graph neural networks",
            "graph neural networks 局限",
        ]
        notes.sort(key=lambda page: page.round_index)
        assert notes[0].queries == ["graph neural networks"]
        assert notes[1].queries == ["graph neural networks 局限"]
        assert coverage is not None and plan_row is not None and review is not None
        spec = ResearchSpec.model_validate(
            (await _plan_spec(factory, run_id)).spec_json
        )
        report = CoverageReport.model_validate(coverage.payload_json)
        limitation = next(
            column.column_id for column in spec.columns if column.field == "limitation"
        )
        assert any(
            cell.column_id == limitation and cell.filled_papers == 0 for cell in report.cells
        )
        bundle = ReviewBundle.model_validate(review.payload_json)
        evidence_ids = {item.evidence_id for item in bundle.review.evidence}
        assert evidence_ids
        async with factory() as session:
            claim_ids = set(
                await session.scalars(select(Claim.evidence_id).where(Claim.run_id == run_id))
            )
            source_requests = (await session.get(Run, run_id)).used_source_requests
            model_calls = await session.scalar(
                select(func.count()).select_from(ModelCall).where(ModelCall.run_id == run_id)
            )
        assert evidence_ids <= claim_ids
        plan_id = UUID(str(ResearchPlan.model_validate(plan_row.payload_json).plan_id))
        await _replay(engine, factory, settings, run_id, plan_id, source_requests, model_calls)

        async with factory.begin() as session:
            source = await session.scalar(
                select(PaperSource).where(
                    PaperSource.provider == "mock", PaperSource.provider_id == "paper-3"
                )
            )
            assert source is not None
            member = await session.get(ProjectPaper, (project_id, source.paper_id))
            assert member is not None
            member.user_decision = "exclude"
            excluded_id = source.paper_id
        second = await start_research(services, project_id, StartResearch(), "coverage-next")
        second_id = UUID(str(second["id"]))
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            await _complete(engine, factory, settings, services, saver, second_id)
        async with factory() as session:
            stored = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == second_id,
                    Artifact.operation_key == f"coverage-round:{second_id}:0",
                )
            )
            assert stored is not None
            assert stored.operation_key == f"coverage-round:{second_id}:0"
            found = {
                paper.paper_id
                for paper in RetrievalResult.model_validate(stored.payload_json).records
            }
        assert excluded_id not in found
    finally:
        await engine.dispose()


async def _plan_spec(factory, run_id: UUID):
    from app.db import ResearchPlan as PlanRow

    async with factory() as session:
        run = await session.get(Run, run_id)
        return await session.get(PlanRow, run.plan_id)


async def _complete(engine, factory, settings, services, saver, run_id: UUID) -> None:
    lease = await claim_next_run(factory, "coverage-worker", run_id)
    assert lease
    status = await execute_run(engine, factory, settings, saver, lease)
    assert status == "waiting_user", await get_status(services, run_id)
    planned = await get_plan(services, run_id)
    plan = ResearchPlan.model_validate(planned["plan"])
    await approve_plan(
        services,
        run_id,
        ApprovePlan(expected_version=plan.version, plan=None),
        f"approve-{run_id}",
    )
    resumed = await claim_next_run(factory, "coverage-worker", run_id)
    assert resumed
    status = await execute_run(engine, factory, settings, saver, resumed)
    assert status == "completed", await get_status(services, run_id)


async def _replay(engine, factory, settings, run_id, plan_id, source_requests, model_calls) -> None:
    token = uuid4()
    async with factory.begin() as session:
        run = await session.get(Run, run_id)
        run.status = "running"
        run.worker_id = "replay"
        run.claim_token = token
    lease = RunLease(run_id, "replay", token)
    business = fenced_factory(engine, lease)
    context = AgentContext(
        run_id,
        plan_id,
        ModelGateway(
            BudgetService(business),
            MockModelTransport(PROJECT_ROOT / "backend" / "fixtures" / "model"),
            settings,
        ),
        BudgetService(business),
        settings,
        RepositoryAccess(business),
    )
    nodes = WorkflowNodes(context, factory, lease)
    try:
        for index in (0, 1):
            state = initial_state(str(run_id))
            state["plan_id"] = str(plan_id)
            state["round_index"] = index
            await propose(nodes, state)
            await execute_round(nodes, state)
    finally:
        async with factory.begin() as session:
            run = await session.get(Run, run_id)
            assert run.used_source_requests == source_requests
            calls = await session.scalar(
                select(func.count()).select_from(ModelCall).where(ModelCall.run_id == run_id)
            )
            assert calls == model_calls
            run.status = "completed"
            run.worker_id = None
            run.claim_token = None
