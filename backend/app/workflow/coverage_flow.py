import hashlib
import json
from uuid import UUID

import httpx
from langgraph.types import interrupt
from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import Settings
from app.db import Artifact, Claim, Evidence, Project, ProjectPaper, Run, Task
from app.db import ResearchPlan as PlanRow
from app.documents.reading_service import ReadingService
from app.errors import DomainError
from app.memory.coverage import compile_coverage
from app.memory.ledger import EXPERIMENTAL_FIELDS, record_claim
from app.planning.admit import AdmissionResult, PaperAdmission, admit_actions
from app.planning.planner import draft_research_spec, propose_round
from app.planning.spec import allowed_sources_for, normalize_spec
from app.repositories.artifacts import ArtifactRepository
from app.repositories.papers import PaperRepository
from app.schemas.contracts import (
    ClaimRecord,
    CoverageReport,
    NotebookPage,
    PaperRecord,
    PlanRequest,
    ReadingCard,
    ResearchPlan,
    ResearchSpec,
    RetrievalResult,
    RoundPlan,
    SearchQuery,
    SelectionResult,
    SourceRecord,
)
from app.screening.service import ScreeningBundle, screen_and_select
from app.sources.factory import build_sources
from app.sources.normalize import normalize_doi
from app.tools.search_works import search_works
from app.worker.claim import lock_owned
from app.workflow.literature import manual_materials
from app.workflow.nodes import WorkflowNodes
from app.workflow.state import ResearchState


class RoundReading(BaseModel):
    artifact_ids: list[UUID]


async def draft_spec(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("plan")
    async with nodes.factory() as session:
        run = await lock_owned(session, nodes.lease)
        inputs, project_id = run.input_snapshot, run.project_id
        existing = await session.scalar(
            select(Artifact).where(
                Artifact.run_id == run.id, Artifact.operation_key == "plan:initial"
            )
        )
    if existing is not None:
        return {"plan_id": str(existing.payload_json["plan_id"]), "stage": "approve_plan"}
    request = PlanRequest.model_validate(inputs["request"])
    draft = await draft_research_spec(request, nodes.context)
    spec = normalize_spec(draft, request, allowed_sources_for(nodes.context.settings))
    async with nodes.context.require_repositories().factory.begin() as session:
        await session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        version = (
            await session.scalar(
                select(func.max(PlanRow.version)).where(PlanRow.project_id == project_id)
            )
            or 0
        ) + 1
        row = PlanRow(
            project_id=project_id,
            version=version,
            questions_json=[question.model_dump(mode="json") for question in spec.questions],
            scope_json=spec.scope.model_dump(mode="json"),
            spec_json=spec.model_dump(mode="json"),
        )
        session.add(row)
        await session.flush()
        plan = ResearchPlan(
            topic=spec.topic,
            questions=spec.questions,
            scope=spec.scope,
            assumptions=spec.assumptions,
            plan_id=row.id,
            project_id=project_id,
            version=version,
        )
        payload = plan.model_dump(mode="json")
        digest = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        repo = ArtifactRepository(session)
        await repo.get_or_create(nodes.context.run_id, f"plan:{row.id}", "plan", payload, digest)
        await repo.get_or_create(nodes.context.run_id, "plan:initial", "plan", payload, digest)
        run = await lock_owned(session, nodes.lease)
        run.plan_id = row.id
    return {"plan_id": str(plan.plan_id), "stage": "approve_plan", "round_index": 0}


def freeze_snapshot_fields(settings: Settings, enabled_sources: list[str]) -> dict[str, object]:
    """确认成功时写入两份快照的同一组字段。"""
    return {
        "planner_mode": settings.planner_mode,
        "max_research_rounds": settings.max_research_rounds,
        "max_actions_per_round": settings.max_actions_per_round,
        "max_citation_neighbors": settings.max_citation_neighbors,
        "max_search_in_paper_calls_per_paper": settings.max_search_in_paper_calls_per_paper,
        "embedding_mode": settings.embedding_mode,
        "enabled_sources": list(enabled_sources),
        "max_source_requests": settings.max_source_requests,
        "max_llm_calls": settings.max_llm_calls,
        "max_deep_read_papers": settings.max_deep_read_papers,
    }


async def approve_spec(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("approve_plan")
    plan = await nodes.get_plan(state)
    approved = interrupt({"type": "approve_spec", "plan": plan.model_dump(mode="json")})
    if not isinstance(approved, dict) or approved.get("approved") is not True:
        raise DomainError("PLAN_NOT_APPROVED", "需要有效的计划确认。")
    plan_id = UUID(str(approved.get("plan_id", state["plan_id"])))
    async with nodes.factory.begin() as session:
        run = await lock_owned(session, nodes.lease)
        row = await session.get(PlanRow, plan_id)
        if (
            row is None
            or row.project_id != run.project_id
            or row.confirmed_at is None
            or row.spec_json is None
            or run.plan_id != plan_id
        ):
            raise DomainError("PLAN_NOT_APPROVED", "提交的计划版本未由服务确认。")
        spec = ResearchSpec.model_validate(row.spec_json)
        frozen = freeze_snapshot_fields(nodes.context.settings, spec.scope.enabled_sources)
        run.input_snapshot = {**run.input_snapshot, **frozen}
        run.config_snapshot = {**run.config_snapshot, **frozen}
    return {"plan_id": str(plan_id), "stage": "begin_round", "round_index": 0, "stop_reason": ""}


async def begin_round(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("begin_round")
    plan = await nodes.get_plan(state)
    spec = await _spec(nodes, plan.plan_id)
    claims = await _claims(nodes, plan.project_id)
    previous, consecutive, new_relevant = await _coverage_history(nodes, state["round_index"])
    remaining = await _remaining(nodes, plan.project_id)
    report = compile_coverage(
        spec,
        claims,
        round_index=state["round_index"],
        new_relevant_papers=new_relevant,
        previously_filled_required_cells=previous,
        consecutive_saturated_rounds=consecutive,
        remaining_source_requests=remaining[0],
        remaining_llm_calls=remaining[1],
        remaining_deep_reads=remaining[2],
    )
    identifier = await nodes.save(_coverage_key(nodes, state["round_index"]), "coverage", report)
    return {"coverage_artifact_id": str(identifier), "stage": "propose"}


async def propose(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("propose")
    key = _plan_key(nodes, state["round_index"])
    if await _artifact(nodes, key) is not None:
        return {"stage": "execute"}
    plan = await nodes.get_plan(state)
    spec = await _spec(nodes, plan.plan_id)
    coverage = await nodes.load(state["coverage_artifact_id"], CoverageReport)
    round_plan = await propose_round(spec, coverage, state["round_index"], nodes.context)
    await nodes.save(key, "round_plan", round_plan)
    return {"stage": "execute"}


async def execute(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("execute")
    key = _retrieval_key(nodes, state["round_index"])
    saved = await _artifact(nodes, key)
    if saved is not None:
        return {
            "retrieval_artifact_id": str(saved.id),
            "stage": "screen_new",
            "stop_reason": await _saved_stop(nodes, state),
        }
    plan = await nodes.get_plan(state)
    spec = await _spec(nodes, plan.plan_id)
    coverage = await nodes.load(state["coverage_artifact_id"], CoverageReport)
    papers = await _admissions(nodes, plan.project_id)
    remaining = await _remaining(nodes, plan.project_id)
    stored_plan = await _require(nodes, _plan_key(nodes, state["round_index"]))
    round_plan = RoundPlan.model_validate(stored_plan.payload_json)
    admission = admit_actions(
        spec,
        round_plan.actions,
        coverage,
        papers,
        remaining_source_requests=remaining[0],
        remaining_llm_calls=remaining[1],
        remaining_deep_reads=remaining[2],
        max_actions_per_round=nodes.context.settings.max_actions_per_round,
        max_citation_neighbors=nodes.context.settings.max_citation_neighbors,
        max_search_in_paper_calls_per_paper=(
            nodes.context.settings.max_search_in_paper_calls_per_paper
        ),
    )
    await nodes.save(_admission_key(nodes, state["round_index"]), "admission", admission)
    queries = [
        SearchQuery(
            query_id=f"round-{state['round_index']}-{index}",
            question_ids=action.question_ids,
            provider=action.providers[0],
            terms=action.query or "",
            year_from=spec.scope.year_from,
            year_to=spec.scope.year_to,
            languages=spec.scope.languages,
        )
        for index, action in enumerate(admission.actions)
        if action.kind == "search_works" and action.query and action.providers
    ]
    records: list[PaperRecord] = []
    warnings: list[str] = []
    if queries:
        for _query in queries:
            await nodes.context.budget.reserve_source_request(
                nodes.context.run_id, nodes.context.settings.max_source_requests
            )
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            found = await search_works(
                queries, build_sources(nodes.context.settings, client), limit=20
            )
        warnings.extend(found.warnings)
        records = await _persist(nodes, found.records, plan.project_id)
        await _remember_queries(nodes, state["round_index"], queries, records)
    _, _, excluded = await manual_materials(nodes.context, plan.project_id)
    result = RetrievalResult(
        records=[paper for paper in records if paper.paper_id not in excluded],
        warnings=list(dict.fromkeys(warnings)),
    )
    identifier = await nodes.save(key, "retrieval", result)
    stop = "stop" if any(action.kind == "stop" for action in admission.actions) else ""
    if admission.stop_reason and not admission.actions:
        stop = admission.stop_reason
    return {"retrieval_artifact_id": str(identifier), "stage": "screen_new", "stop_reason": stop}


async def screen_new(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("screen")
    key = f"coverage-screen:{nodes.context.run_id}:{state['round_index']}"
    saved = await _artifact(nodes, key)
    if saved is not None:
        bundle = ScreeningBundle.model_validate(saved.payload_json)
        return {
            "screening_artifact_id": str(saved.id),
            "selection_artifact_id": str(bundle.selection_artifact_id),
            "stage": "read_selected",
        }
    plan = await nodes.get_plan(state)
    retrieved = await nodes.load(state["retrieval_artifact_id"], RetrievalResult)
    _, manual_ids, excluded = await manual_materials(nodes.context, plan.project_id)
    records = [paper for paper in retrieved.records if paper.paper_id not in excluded]
    present = {paper.paper_id for paper in records}
    manual_ids = [identifier for identifier in manual_ids if identifier in present]
    bundle = await screen_and_select(records, plan, nodes.context, manual_ids)
    stop = next(
        (
            item
            for item in bundle.failures
            if item["code"]
            in {
                "BUDGET_EXHAUSTED",
                "MODEL_TIMEOUT_UNKNOWN",
                "UNRESOLVED_MODEL_CALLS",
                "RUN_CANCELLED",
            }
        ),
        None,
    )
    if stop:
        raise DomainError(stop["code"], stop["message"])
    identifier = await nodes.save(key, "screening_bundle", bundle)
    return {
        "screening_artifact_id": str(identifier),
        "selection_artifact_id": str(bundle.selection_artifact_id),
        "stage": "read_selected",
    }


async def read_selected(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("read")
    key = f"coverage-reading:{nodes.context.run_id}:{state['round_index']}"
    saved = await _artifact(nodes, key)
    if saved is not None:
        stored = RoundReading.model_validate(saved.payload_json)
        return {
            "reading_artifact_ids": [str(item) for item in stored.artifact_ids],
            "stage": "note",
        }
    plan = await nodes.get_plan(state)
    retrieved = await nodes.load(state["retrieval_artifact_id"], RetrievalResult)
    selection = await nodes.load(state["selection_artifact_id"], SelectionResult)
    reading = await ReadingService(nodes.context).read_selected(retrieved.records, selection, plan)
    spec = await _spec(nodes, plan.plan_id)
    await _record_reading_claims(nodes, plan, spec, reading.cards)
    accumulated = list(
        dict.fromkeys([*state["reading_artifact_ids"], *map(str, reading.artifact_ids)])
    )
    await nodes.save(
        key, "coverage_reading", RoundReading(artifact_ids=[UUID(item) for item in accumulated])
    )
    return {"reading_artifact_ids": accumulated, "stage": "note"}


async def note(nodes: WorkflowNodes, state: ResearchState) -> dict[str, object]:
    await nodes.enter("note")
    key = f"coverage-note:{nodes.context.run_id}:{state['round_index']}"
    saved = await _artifact(nodes, key)
    page = (
        NotebookPage.model_validate(saved.payload_json)
        if saved is not None
        else await _page(nodes, state)
    )
    if saved is None:
        saved_id = await nodes.save(key, "notebook", page)
    else:
        saved_id = saved.id
    identifier = str(saved_id)
    notebooks = state["notebook_ids"]
    if identifier not in notebooks:
        notebooks = [*notebooks, identifier]
    index = state["round_index"] + 1
    stop = state["stop_reason"]
    if not stop and index >= nodes.context.settings.max_research_rounds:
        stop = "rounds"
    return {
        "notebook_ids": notebooks,
        "round_index": index,
        "stop_reason": stop,
        "stage": "write" if stop else "begin_round",
    }


async def _page(nodes: WorkflowNodes, state: ResearchState) -> NotebookPage:
    coverage = await nodes.load(state["coverage_artifact_id"], CoverageReport)
    retrieval = await nodes.load(state["retrieval_artifact_id"], RetrievalResult)
    admission_row = await _artifact(nodes, _admission_key(nodes, state["round_index"]))
    admission = (
        AdmissionResult.model_validate(admission_row.payload_json)
        if admission_row is not None
        else AdmissionResult(actions=[], rejected=[])
    )
    return NotebookPage(
        round_index=state["round_index"],
        executed_action_ids=[action.action_id for action in admission.actions],
        rejected_actions=[
            {"action_id": item.action_id, "reason": item.reason} for item in admission.rejected
        ],
        new_paper_ids=[paper.paper_id for paper in retrieval.records],
        filled_column_ids=[cell.column_id for cell in coverage.cells if cell.filled_papers > 0],
        open_gaps=list(coverage.unmet_question_ids),
        queries=[action.query for action in admission.actions if action.query],
        index_mode="bm25" if nodes.context.settings.embedding_mode == "off" else "hybrid",
    )


def _coverage_key(nodes: WorkflowNodes, round_index: int) -> str:
    return f"coverage:{nodes.context.run_id}:{round_index}"


def _plan_key(nodes: WorkflowNodes, round_index: int) -> str:
    return f"coverage-plan:{nodes.context.run_id}:{round_index}"


def _retrieval_key(nodes: WorkflowNodes, round_index: int) -> str:
    return f"coverage-round:{nodes.context.run_id}:{round_index}"


def _admission_key(nodes: WorkflowNodes, round_index: int) -> str:
    return f"coverage-admission:{nodes.context.run_id}:{round_index}"


async def _artifact(nodes: WorkflowNodes, key: str) -> Artifact | None:
    async with nodes.factory() as session:
        return await session.scalar(
            select(Artifact).where(
                Artifact.run_id == nodes.context.run_id, Artifact.operation_key == key
            )
        )


async def _require(nodes: WorkflowNodes, key: str) -> Artifact:
    artifact = await _artifact(nodes, key)
    if artifact is None:
        raise DomainError("ARTIFACT_NOT_FOUND", "缺少前序成果。")
    return artifact


async def _spec(nodes: WorkflowNodes, plan_id: UUID) -> ResearchSpec:
    async with nodes.factory() as session:
        row = await session.get(PlanRow, plan_id)
        if row is None or row.spec_json is None:
            raise DomainError("PLAN_NOT_FOUND", "研究规格未保存。")
        return ResearchSpec.model_validate(row.spec_json)


async def _claims(nodes: WorkflowNodes, project_id: UUID) -> list[ClaimRecord]:
    async with nodes.factory() as session:
        rows = list(
            await session.scalars(select(Claim).where(Claim.project_id == project_id))
        )
    return [
        ClaimRecord.model_validate(
            {
                "claim_id": row.id,
                "paper_id": row.paper_id,
                "question_id": row.question_id,
                "column_id": row.column_id,
                "evidence_id": row.evidence_id,
                "polarity": row.polarity,
                "value_zh": row.value_zh,
            }
        )
        for row in rows
        if row.polarity in {"support", "contradict"}
    ]


async def _coverage_history(
    nodes: WorkflowNodes, round_index: int
) -> tuple[set[tuple[str, str]], int, int]:
    if round_index == 0:
        return set(), 0, 0
    previous = await _artifact(nodes, _coverage_key(nodes, round_index - 1))
    retrieval = await _artifact(nodes, _retrieval_key(nodes, round_index - 1))
    if previous is None:
        return set(), 0, 0
    report = CoverageReport.model_validate(previous.payload_json)
    filled = {
        (cell.question_id, cell.column_id)
        for cell in report.cells
        if cell.required and cell.filled_papers > 0
    }
    count = 0
    if retrieval is not None:
        count = len(RetrievalResult.model_validate(retrieval.payload_json).records)
    return filled, report.consecutive_saturated_rounds, count


async def _remaining(nodes: WorkflowNodes, project_id: UUID) -> tuple[int, int, int]:
    del project_id
    settings = nodes.context.settings
    async with nodes.factory() as session:
        run = await session.get(Run, nodes.context.run_id)
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        read_count = await session.scalar(
            select(func.count(func.distinct(Artifact.paper_id))).where(
                Artifact.run_id == run.id,
                Artifact.kind == "reading",
                Artifact.paper_id.is_not(None),
            )
        )
    source = max(
        0,
        settings.max_source_requests - run.used_source_requests - run.reserved_source_requests,
    )
    calls = max(0, run.max_calls - run.used_calls - run.reserved_calls)
    reads = max(0, settings.max_deep_read_papers - int(read_count or 0))
    return source, calls, reads


async def _admissions(nodes: WorkflowNodes, project_id: UUID) -> list[PaperAdmission]:
    async with nodes.factory() as session:
        members = list(
            await session.scalars(
                select(ProjectPaper).where(ProjectPaper.project_id == project_id)
            )
        )
    return [
        PaperAdmission(
            paper_id=member.paper_id,
            status="excluded" if member.user_decision == "exclude" else "active",
        )
        for member in members
    ]


async def _saved_stop(nodes: WorkflowNodes, state: ResearchState) -> str:
    row = await _artifact(nodes, _admission_key(nodes, state["round_index"]))
    if row is None:
        return state["stop_reason"]
    admission = AdmissionResult.model_validate(row.payload_json)
    if any(action.kind == "stop" for action in admission.actions):
        return "stop"
    if admission.stop_reason and not admission.actions:
        return admission.stop_reason
    return state["stop_reason"]


async def _persist(
    nodes: WorkflowNodes, records: list[PaperRecord], project_id: UUID
) -> list[PaperRecord]:
    factory = nodes.context.require_repositories().factory
    stored: list[PaperRecord] = []
    seen: set[UUID] = set()
    for record in records:
        async with factory.begin() as session:
            repo = PaperRepository(session)
            record_id: UUID | None = None
            abstract_source_id: UUID | None = None
            persisted: list[SourceRecord] = []
            for original in record.sources:
                saved = await repo.upsert_source(
                    original.provider,
                    original.provider_id,
                    original.version_label,
                    record.title,
                    normalize_doi(record.doi),
                    original.abstract,
                    original.raw_payload,
                    year=record.year,
                    authors=record.authors,
                    metadata=original.model_dump(mode="json", exclude={"raw_payload"}),
                )
                record_id = record_id or saved.paper_id
                persisted.append(original.model_copy(update={"source_id": saved.id}))
                if original.source_key == record.abstract_source_key:
                    abstract_source_id = saved.id
            if record_id is None or record_id in seen:
                continue
            await repo.attach(project_id, record_id)
        seen.add(record_id)
        stored.append(
            record.model_copy(
                update={
                    "paper_id": record_id,
                    "source_id": abstract_source_id,
                    "doi": normalize_doi(record.doi),
                    "sources": persisted,
                }
            )
        )
    return stored


async def _remember_queries(
    nodes: WorkflowNodes,
    round_index: int,
    queries: list[SearchQuery],
    records: list[PaperRecord],
) -> None:
    factory = nodes.context.require_repositories().factory
    async with factory.begin() as session:
        for query in queries:
            payload = {"query": query.model_dump(mode="json"), "cursor": None, "limit": 20}
            session.add(
                Task(
                    run_id=nodes.context.run_id,
                    role="retrieval",
                    operation="source_search",
                    status="completed",
                    input_hash=hashlib.sha256(
                        json.dumps(payload, sort_keys=True).encode()
                    ).hexdigest(),
                    client_request_key=f"{round_index}:{query.query_id}",
                    input_json=payload,
                    output_json={
                        "paper_ids": [str(paper.paper_id) for paper in records],
                        "count": len(records),
                    },
                )
            )


async def _record_reading_claims(
    nodes: WorkflowNodes,
    plan: ResearchPlan,
    spec: ResearchSpec,
    cards: list[ReadingCard],
) -> None:
    method = next((column for column in spec.columns if column.field == "method"), None)
    if method is None:
        return
    async with nodes.context.require_repositories().factory.begin() as session:
        for card in cards:
            for field_name, facts in card.fields.items():
                column = next(
                    (item for item in spec.columns if item.field == field_name), method
                )
                for fact in facts:
                    for evidence_id in fact.evidence_ids:
                        evidence = await session.get(Evidence, evidence_id)
                        if evidence is None or evidence.paper_id != card.paper_id:
                            continue
                        if evidence.basis == "abstract" and column.field in EXPERIMENTAL_FIELDS:
                            continue
                        await record_claim(
                            session,
                            project_id=plan.project_id,
                            run_id=nodes.context.run_id,
                            paper_id=card.paper_id,
                            question_id=column.question_id,
                            column_id=column.column_id,
                            column_field=column.field,
                            evidence_id=evidence_id,
                            polarity="support",
                            value_zh=fact.value_zh,
                        )
