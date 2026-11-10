from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import select

from app.agents.context import AgentContext, RepositoryAccess
from app.agents.reading import ReadingAgent
from app.config import PROJECT_ROOT
from app.db import Artifact, ModelCall, PaperSource, Run
from app.db import ResearchPlan as PlanRow
from app.db.session import create_engine, get_test_settings, session_factory
from app.evaluation import runner
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.repositories.papers import PaperRepository
from app.schemas.contracts import PaperRecord, PlanDraft, ResearchPlan, SearchPage, SourceRecord
from app.services.base import Services
from app.services.literature import SearchRequest, submit_search
from app.services.projects import create_project
from app.services.research import StartResearch, start_research
from app.worker.claim import claim_next_run
from app.workflow.literature import drain_search_tasks
from app.workflow.nodes import WorkflowNodes
from app.workflow.recovery import recover_run
from app.workflow.state import initial_state


@pytest_asyncio.fixture
async def case():
    settings = get_test_settings()
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    project = await create_project(services, "最终审查回归", "synthetic")
    accepted = await start_research(services, UUID(str(project["id"])), StartResearch(), "initial")
    run_id = UUID(str(accepted["id"]))
    draft = PlanDraft.model_validate_json(
        (PROJECT_ROOT / "backend/fixtures/model/PlanDraft.json").read_text(encoding="utf-8")
    )
    async with factory.begin() as session:
        row = PlanRow(
            project_id=UUID(str(project["id"])),
            version=1,
            confirmed_at=datetime.now(UTC),
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
        run.plan_id = row.id
    budget = BudgetService(factory)
    context = AgentContext(
        run_id,
        plan.plan_id,
        ModelGateway(budget, MockModelTransport(PROJECT_ROOT / "backend/fixtures/model"), settings),
        budget,
        settings,
        RepositoryAccess(factory),
    )
    try:
        yield settings, factory, services, plan, context, run_id
    finally:
        await engine.dispose()


class AdditionalSource:
    def __init__(self):
        self.calls = 0
        self.identifier = str(uuid4())

    async def search(self, query, cursor=None, limit=100):
        self.calls += 1
        return SearchPage(
            records=[
                PaperRecord(
                    title="Additional paper absent from main search",
                    sources=[
                        SourceRecord(
                            provider="fixture", provider_id=self.identifier, version_label="v1"
                        )
                    ],
                )
            ],
            raw_count=1,
        )


async def open_retrieval(factory, run_id):
    lease = await claim_next_run(factory, "review-test", run_id)
    async with factory.begin() as session:
        run = await session.get(Run, run_id)
        run.stage, run.retrieval_accepting = "retrieve", True
    return lease


async def test_completed_extra_search_is_replayed_without_another_source_request(case):
    settings, factory, services, plan, context, run_id = case
    lease = await open_retrieval(factory, run_id)
    await submit_search(
        services,
        plan.project_id,
        run_id,
        SearchRequest(query="extra", question_ids=["q1"]),
        "extra",
    )
    source = AdditionalSource()
    first = await drain_search_tasks(context, factory, lease, plan, {"openalex": source})
    # Both crash windows (before/after bundle save) must reconstruct this exact business result.
    resumed = await drain_search_tasks(context, factory, lease, plan, {"openalex": source})
    assert [result.model_dump(mode="json") for result in resumed] == [
        result.model_dump(mode="json") for result in first
    ]
    assert len(resumed[0].records) == 1 and source.calls == 1
    # A second crash window: bundle saved, checkpoint not yet saved. No reopened gate.
    async with factory.begin() as session:
        saved = Artifact(
            run_id=run_id,
            kind="retrieval_bundle",
            operation_key="workflow:retrieval:0",
            input_hash="persisted",
            payload_json=first[0].model_dump(mode="json"),
        )
        session.add(saved)
        await session.flush()
        artifact_id = saved.id
    state = initial_state(str(run_id))
    state["plan_id"] = str(plan.plan_id)
    replayed = await WorkflowNodes(context, factory, lease).retrieve(state)
    assert replayed["retrieval_artifact_id"] == str(artifact_id)
    async with factory() as session:
        run = await session.get(Run, run_id)
        assert not run.retrieval_accepting and run.used_source_requests == 1


async def test_unexecuted_extra_search_reports_budget_exhausted_instead_of_empty_success(case):
    settings, factory, services, plan, context, run_id = case
    lease = await open_retrieval(factory, run_id)
    task = await submit_search(
        services,
        plan.project_id,
        run_id,
        SearchRequest(query="extra", question_ids=["q1"]),
        "budget",
    )
    async with factory.begin() as session:
        run = await session.get(Run, run_id)
        run.used_source_requests = settings.max_source_requests
    source = AdditionalSource()
    await drain_search_tasks(context, factory, lease, plan, {"openalex": source})
    from app.db import Task

    async with factory() as session:
        stored = await session.get(Task, UUID(str(task["id"])))
        assert stored.status == "budget_exhausted"
        assert stored.error_json["code"] == "BUDGET_EXHAUSTED"
    assert source.calls == 0


async def test_pre_send_reservation_recovers_and_reuses_same_unbilled_attempt(case):
    settings, factory, services, plan, context, run_id = case
    reservation = await context.budget.reserve_call(run_id, "before-send", "hash", 100)
    async with factory.begin() as session:
        run = await session.get(Run, run_id)
        run.status = "interrupted"
    await recover_run(factory, run_id, None, True)
    async with factory() as session:
        run = await session.get(Run, run_id)
        assert run.status == "queued" and run.used_calls == 0
        assert run.reserved_calls == run.reserved_tokens == 0
    resumed = await context.budget.reserve_call(run_id, "before-send", "hash", 100)
    assert resumed.call_id == reservation.call_id and resumed.attempt == reservation.attempt


async def test_new_abstract_version_uses_new_model_operation_then_caches_it(case):
    settings, factory, services, plan, context, run_id = case
    paper = PaperRecord(
        title="Synthetic retrieval",
        abstract="Graph retrieval v1",
        abstract_status="provided",
        sources=[SourceRecord(provider="mock", provider_id="paper-1", version_label="v1")],
    )
    await ReadingAgent().screen(paper, plan, context)
    newer = paper.model_copy(
        update={"abstract": "Graph retrieval with an updated original abstract v2"}
    )
    await ReadingAgent().screen(newer, plan, context)
    await ReadingAgent().screen(newer, plan, context)
    async with factory() as session:
        calls = list(await session.scalars(select(ModelCall).where(ModelCall.run_id == run_id)))
        assert len(calls) == 2 and len({call.operation_key for call in calls}) == 2


async def test_evaluation_identity_uses_current_corpus_instead_of_other_sources(case):
    settings, factory, services, plan, context, run_id = case
    identifier, other = str(uuid4()), str(uuid4())
    doi = f"10.5555/{uuid4()}"
    original = SourceRecord(
        provider="frozen", provider_id=identifier, version_label="v1", abstract="Original abstract"
    )
    paper = PaperRecord(
        title="Frozen identity", doi=doi, abstract=original.abstract, sources=[original]
    )
    async with factory.begin() as session:
        repo = PaperRepository(session)
        first = await repo.upsert_source(
            "frozen", identifier, "v1", paper.title, doi, original.abstract, {}
        )
        await repo.upsert_source("other", other, "v1", paper.title, doi, "Other source", {})
        await repo.upsert_source(
            "frozen", identifier, "v0", paper.title, doi, "Historical abstract", {}
        )
        paper_id = first.paper_id
    async with factory() as session:
        sources = list(
            await session.scalars(select(PaperSource).where(PaperSource.paper_id == paper_id))
        )
        mapping = runner.corpus_identity_map([paper], sources, {original.source_key})
    assert mapping[str(paper_id)] == original.source_key


async def test_idempotent_retry_does_not_change_frozen_budget_after_server_config_change(case):
    settings, factory, services, plan, context, run_id = case
    changed = Services(
        settings.model_copy(
            update={
                "max_llm_calls": settings.max_llm_calls + 100,
                "max_estimated_total_tokens": settings.max_estimated_total_tokens + 100000,
            }
        ),
        factory,
    )
    response = await start_research(changed, plan.project_id, StartResearch(), "initial")
    assert response["max_calls"] == settings.max_llm_calls
    assert response["max_tokens"] == settings.max_estimated_total_tokens
