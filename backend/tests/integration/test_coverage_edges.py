import json
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.agents.context import AgentContext, RepositoryAccess
from app.config import PROJECT_ROOT
from app.db import Artifact, Claim, Document, PaperNeighbor, ProjectPaper, Run, Task
from app.db.session import create_engine, get_test_settings, session_factory
from app.llm.budget import BudgetService
from app.llm.gateway import ModelGateway
from app.llm.mock import MockModelTransport
from app.planning.admit import AdmissionResult
from app.repositories.papers import PaperRepository
from app.schemas.contracts import (
    CoverageReport,
    NotebookPage,
    ResearchPlan,
    ResearchSpec,
    RetrievalResult,
    RoundAction,
    RoundPlan,
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
from app.workflow import coverage_flow
from app.workflow.coverage_flow import _admissions, begin_round, execute, note
from app.workflow.nodes import WorkflowNodes
from app.workflow.state import initial_state


@pytest.mark.xfail(strict=True, reason="第0轮尚未检索时覆盖表被标成饱和")
async def test_round_zero_is_not_saturated_while_questions_remain():
    run = await _finished(2)
    try:
        report = await _coverage(run, 0)
        assert report.unmet_question_ids
        assert report.saturated is False
        assert report.consecutive_saturated_rounds == 0
    finally:
        await run.engine.dispose()


@pytest.mark.xfail(strict=True, reason="重复命中的已入库论文仍被计为新论文")
async def test_repeat_hits_are_not_new_relevant_papers():
    run = await _finished(2)
    try:
        async with run.factory() as session:
            stored = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run.run_id,
                    Artifact.operation_key == f"coverage-round:{run.run_id}:1",
                )
            )
        assert stored is not None
        previous = RetrievalResult.model_validate(stored.payload_json)
        assert previous.records
        nodes = await _reopen(run)
        state = initial_state(str(run.run_id))
        state["plan_id"] = str(run.plan_id)
        state["round_index"] = 2
        opened = await begin_round(nodes, state)
        report = await nodes.load(opened["coverage_artifact_id"], CoverageReport)
        assert report.new_relevant_papers_last_round == 0
    finally:
        await run.engine.dispose()


@pytest.mark.xfail(strict=True, reason="最后一轮阅读写入的主张没有进入覆盖表")
async def test_latest_coverage_includes_claims_from_the_final_read():
    run = await _finished(1)
    try:
        async with run.factory() as session:
            claims = list(await session.scalars(select(Claim).where(Claim.run_id == run.run_id)))
            artifacts = list(
                await session.scalars(
                    select(Artifact).where(
                        Artifact.run_id == run.run_id, Artifact.kind == "coverage"
                    )
                )
            )
        assert claims
        latest = max(artifacts, key=lambda item: int(item.payload_json["round_index"]))
        report = CoverageReport.model_validate(latest.payload_json)
        for cell in report.cells:
            if not cell.required:
                continue
            papers = {
                claim.paper_id
                for claim in claims
                if claim.question_id == cell.question_id and claim.column_id == cell.column_id
            }
            assert cell.filled_papers == len(papers)
        assert any(cell.required and cell.filled_papers > 0 for cell in report.cells)
    finally:
        await run.engine.dispose()


@pytest.mark.xfail(strict=True, reason="来源异常在产物保存前失败，重试会再次扣费")
async def test_source_failure_is_recorded_once(monkeypatch: pytest.MonkeyPatch):
    run = await _approved()
    try:
        nodes = await _reopen(run)
        state = initial_state(str(run.run_id))
        state["plan_id"] = str(run.plan_id)
        state.update(await begin_round(nodes, state))
        state.update(await coverage_flow.propose(nodes, state))

        async def broken(*args, **kwargs):
            raise RuntimeError("source down")

        monkeypatch.setattr(coverage_flow, "search_works", broken)
        state.update(await execute(nodes, state))
        retrieval = await nodes.load(state["retrieval_artifact_id"], RetrievalResult)
        async with run.factory() as session:
            stored = await session.get(Run, run.run_id)
        assert stored is not None
        assert retrieval.warnings
        charged = stored.used_source_requests
        await execute(nodes, state)
        async with run.factory() as session:
            replayed = await session.get(Run, run.run_id)
        assert replayed is not None
        assert replayed.used_source_requests == charged
    finally:
        await run.engine.dispose()


@pytest.mark.xfail(strict=True, reason="未满足时停止被接受，空检索仍进入筛选")
async def test_unmet_stop_does_not_screen_an_empty_round(monkeypatch: pytest.MonkeyPatch):
    run = await _approved()
    calls: list[object] = []
    original = coverage_flow.screen_and_select

    async def only_stop(spec, coverage, round_index, context):
        question_id = (
            coverage.unmet_question_ids[0]
            if coverage.unmet_question_ids
            else spec.questions[0].question_id
        )
        return RoundPlan(
            actions=[
                RoundAction(
                    action_id="stop-0",
                    kind="stop",
                    question_ids=[question_id],
                    rationale="请求停止",
                )
            ]
        )

    async def spy(*args, **kwargs):
        calls.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(coverage_flow, "propose_round", only_stop)
    monkeypatch.setattr(coverage_flow, "screen_and_select", spy)
    try:
        async with AsyncPostgresSaver.from_conn_string(run.settings.checkpoint_dsn) as saver:
            await saver.setup()
            lease = await claim_next_run(run.factory, "coverage-edge", run.run_id)
            assert lease
            await execute_run(run.engine, run.factory, run.settings, saver, lease)
        async with run.factory() as session:
            admission_row = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run.run_id,
                    Artifact.operation_key == f"coverage-admission:{run.run_id}:0",
                )
            )
            retrieval_row = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run.run_id,
                    Artifact.operation_key == f"coverage-round:{run.run_id}:0",
                )
            )
            tasks = list(
                await session.scalars(
                    select(Task).where(Task.run_id == run.run_id, Task.operation == "source_search")
                )
            )
        assert admission_row is not None and retrieval_row is not None
        admission = AdmissionResult.model_validate(admission_row.payload_json)
        retrieval = RetrievalResult.model_validate(retrieval_row.payload_json)
        rejected = {item.reason for item in admission.rejected}
        assert "unmet_coverage" in rejected or tasks
        assert not calls or retrieval.records
    finally:
        await run.engine.dispose()


@pytest.mark.xfail(strict=True, reason="引文动作未执行却记入已执行列表")
async def test_admitted_citation_action_is_executed_before_it_is_noted():
    run = await _finished(1)
    try:
        spec_row = await _plan_row(run)
        async with run.factory() as session:
            member = await session.scalar(
                select(ProjectPaper).where(
                    ProjectPaper.project_id == run.project_id,
                    ProjectPaper.user_decision.is_distinct_from("exclude"),
                )
            )
        assert member is not None and spec_row is not None and spec_row.spec_json is not None
        spec = ResearchSpec.model_validate(spec_row.spec_json)
        nodes = await _reopen(run)
        coverage = await _coverage_artifact(run, 0)
        state = initial_state(str(run.run_id))
        state["plan_id"] = str(run.plan_id)
        state["round_index"] = 1
        state["coverage_artifact_id"] = str(coverage.id)
        await nodes.save(
            f"coverage-plan:{run.run_id}:1",
            "round_plan",
            RoundPlan(
                actions=[
                    RoundAction(
                        action_id="cite-1",
                        kind="expand_citations",
                        question_ids=[spec.questions[0].question_id],
                        rationale="查看参考文献",
                        paper_ids=[member.paper_id],
                        direction="references",
                    )
                ]
            ),
        )
        state.update(await execute(nodes, state))
        await note(nodes, state)
        async with run.factory() as session:
            neighbors = list(
                await session.scalars(
                    select(PaperNeighbor).where(PaperNeighbor.project_id == run.project_id)
                )
            )
            tasks = list(await session.scalars(select(Task).where(Task.run_id == run.run_id)))
            page_row = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run.run_id,
                    Artifact.operation_key == f"coverage-note:{run.run_id}:1",
                )
            )
        assert page_row is not None
        page = NotebookPage.model_validate(page_row.payload_json)
        performed = bool(neighbors) or any(_citation_task(task) for task in tasks)
        assert performed
        assert "cite-1" not in page.executed_action_ids or performed
    finally:
        await run.engine.dispose()


@pytest.mark.xfail(strict=True, reason="准入状态没有带上筛选相关性和文档")
async def test_admission_state_keeps_relevance_and_documents():
    run = await _finished(1)
    try:
        nodes = await _reopen(run)
        admitted = await _admissions(nodes, run.project_id)
        by_paper = {item.paper_id: item for item in admitted}
        async with run.factory() as session:
            screened = list(
                await session.scalars(
                    select(Artifact).where(
                        Artifact.run_id == run.run_id,
                        Artifact.kind == "screening",
                        Artifact.paper_id.is_not(None),
                    )
                )
            )
            documents = list(
                await session.scalars(
                    select(Document).where(Document.owner_project_id == run.project_id)
                )
            )
        assert screened
        for artifact in screened:
            assert artifact.paper_id is not None
            assert by_paper[artifact.paper_id].relevance == artifact.payload_json.get("relevance")
        for document in documents:
            assert by_paper[document.paper_id].has_document is True
    finally:
        await run.engine.dispose()


@pytest.mark.xfail(strict=True, reason="带文档的手动纳入论文没有进入本轮候选")
async def test_included_local_document_enters_the_round_candidates():
    settings = _settings(1)
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    try:
        project = await create_project(services, "手动纳入", "图神经网络文献")
        project_id = UUID(str(project["id"]))
        included = await _include_local_paper(factory, project_id)
        started = await start_research(services, project_id, StartResearch(), f"edge-{uuid4()}")
        run_id = UUID(str(started["id"]))
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
            await saver.setup()
            await _complete(engine, factory, settings, services, saver, run_id)
        async with factory() as session:
            artifacts = list(
                await session.scalars(select(Artifact).where(Artifact.run_id == run_id))
            )
        selected: set[str] = set()
        for artifact in artifacts:
            if artifact.kind in {"preselection", "selection"}:
                selected.update(str(item) for item in artifact.payload_json.get("selected_ids", []))
        assert str(included) in selected
    finally:
        await engine.dispose()


@pytest.mark.xfail(strict=True, reason="来源警告没有写入运行进度")
async def test_source_warnings_are_stored_on_the_run():
    run = await _finished(1)
    try:
        async with run.factory() as session:
            stored = await session.get(Run, run.run_id)
            retrieval_row = await session.scalar(
                select(Artifact).where(
                    Artifact.run_id == run.run_id,
                    Artifact.operation_key == f"coverage-round:{run.run_id}:0",
                )
            )
        assert stored is not None and retrieval_row is not None
        retrieval = RetrievalResult.model_validate(retrieval_row.payload_json)
        recorded = stored.progress_json.get("retrieval_warnings")
        assert retrieval.warnings
        assert isinstance(recorded, list)
        assert set(retrieval.warnings) <= set(recorded)
    finally:
        await run.engine.dispose()


class _Run:
    def __init__(self, engine, factory, settings, services, run_id, project_id, plan_id):
        self.engine = engine
        self.factory = factory
        self.settings = settings
        self.services = services
        self.run_id = run_id
        self.project_id = project_id
        self.plan_id = plan_id


def _settings(max_rounds: int):
    return get_test_settings().model_copy(
        update={"planner_mode": "coverage", "max_research_rounds": max_rounds}
    )


async def _finished(max_rounds: int) -> _Run:
    run = await _approved(max_rounds)
    async with AsyncPostgresSaver.from_conn_string(run.settings.checkpoint_dsn) as saver:
        await saver.setup()
        lease = await claim_next_run(run.factory, "coverage-edge", run.run_id)
        assert lease
        status = await execute_run(run.engine, run.factory, run.settings, saver, lease)
    assert status == "completed", await get_status(run.services, run.run_id)
    return run


async def _approved(max_rounds: int = 2) -> _Run:
    settings = _settings(max_rounds)
    engine = create_engine(settings)
    factory = session_factory(engine)
    services = Services(settings, factory)
    project = await create_project(services, "覆盖边界", "图神经网络文献")
    project_id = UUID(str(project["id"]))
    started = await start_research(services, project_id, StartResearch(), f"edge-{uuid4()}")
    run_id = UUID(str(started["id"]))
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
        await saver.setup()
        lease = await claim_next_run(factory, "coverage-edge", run_id)
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
    async with factory() as session:
        stored = await session.get(Run, run_id)
    assert stored is not None and stored.plan_id is not None
    return _Run(engine, factory, settings, services, run_id, project_id, stored.plan_id)


async def _complete(engine, factory, settings, services, saver, run_id: UUID) -> None:
    lease = await claim_next_run(factory, "coverage-edge", run_id)
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
    resumed = await claim_next_run(factory, "coverage-edge", run_id)
    assert resumed
    status = await execute_run(engine, factory, settings, saver, resumed)
    assert status == "completed", await get_status(services, run_id)


async def _reopen(run: _Run) -> WorkflowNodes:
    token = uuid4()
    async with run.factory.begin() as session:
        stored = await session.get(Run, run.run_id)
        assert stored is not None
        stored.status = "running"
        stored.worker_id = "edge"
        stored.claim_token = token
    lease = RunLease(run.run_id, "edge", token)
    business = fenced_factory(run.engine, lease)
    context = AgentContext(
        run.run_id,
        run.plan_id,
        ModelGateway(
            BudgetService(business),
            MockModelTransport(PROJECT_ROOT / "backend" / "fixtures" / "model"),
            run.settings,
        ),
        BudgetService(business),
        run.settings,
        RepositoryAccess(business),
    )
    return WorkflowNodes(context, run.factory, lease)


async def _coverage(run: _Run, round_index: int) -> CoverageReport:
    artifact = await _coverage_artifact(run, round_index)
    return CoverageReport.model_validate(artifact.payload_json)


async def _coverage_artifact(run: _Run, round_index: int) -> Artifact:
    async with run.factory() as session:
        artifact = await session.scalar(
            select(Artifact).where(
                Artifact.run_id == run.run_id,
                Artifact.operation_key == f"coverage:{run.run_id}:{round_index}",
            )
        )
    assert artifact is not None
    return artifact


async def _plan_row(run: _Run):
    from app.db import ResearchPlan as PlanRow

    async with run.factory() as session:
        return await session.get(PlanRow, run.plan_id)


async def _include_local_paper(factory, project_id: UUID) -> UUID:
    async with factory.begin() as session:
        saved = await PaperRepository(session).upsert_source(
            "upload",
            f"local-{uuid4()}",
            "v1",
            "仅本地纳入的论文",
            None,
            "这篇论文只通过本地文档纳入。",
            {"synthetic": True},
        )
        saved.owner_project_id = project_id
        await PaperRepository(session).attach(project_id, saved.paper_id, "upload")
        member = await session.get(ProjectPaper, (project_id, saved.paper_id))
        assert member is not None
        member.user_decision = "include"
        session.add(
            Document(
                paper_id=saved.paper_id,
                owner_project_id=project_id,
                source_id=saved.id,
                sha256="a" * 64,
                storage_key=f"uploads/{saved.paper_id}.pdf",
                status="parsed",
                page_count=1,
            )
        )
        return saved.paper_id


def _citation_task(task: Task) -> bool:
    blob = json.dumps(task.input_json, ensure_ascii=False)
    return "expand_citations" in task.operation or "cite-1" in blob or "expand_citations" in blob
