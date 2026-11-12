from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.contracts import CoverageReport, ResearchSpec, RoundAction, StrictModel


class PaperAdmission(StrictModel):
    paper_id: UUID
    status: Literal["active", "pinned", "excluded"]
    relevance: int | None = None
    has_document: bool = False
    included: bool = False
    selected_this_round: bool = False
    abstract_missing: bool = False
    search_in_paper_calls: int = 0
    empty_required_column_ids: list[str] = Field(default_factory=list)


class RejectedAction(StrictModel):
    action_id: str
    reason: str


StopReason = Literal["budget_exhausted"]


class AdmissionResult(StrictModel):
    actions: list[RoundAction]
    rejected: list[RejectedAction]
    synthesized_from_gap: RoundAction | None = None
    stop_reason: StopReason | None = None


def admit_actions(
    spec: ResearchSpec,
    actions: list[RoundAction],
    coverage: CoverageReport,
    papers: list[PaperAdmission],
    *,
    remaining_source_requests: int,
    remaining_llm_calls: int,
    remaining_deep_reads: int,
    max_actions_per_round: int = 6,
    max_citation_neighbors: int = 15,
    max_search_in_paper_calls_per_paper: int = 3,
    requested_citation_neighbors: dict[str, int] | None = None,
) -> AdmissionResult:
    library = {item.paper_id: item for item in papers}
    citations = requested_citation_neighbors or {}
    rejected: list[RejectedAction] = []
    valid: list[RoundAction] = []
    for action in actions:
        reason = _structural_reason(
            spec,
            action,
            library,
            citations,
            max_citation_neighbors,
            max_search_in_paper_calls_per_paper,
        )
        if reason is None:
            valid.append(action)
        else:
            rejected.append(RejectedAction(action_id=action.action_id, reason=reason))
    affordable, rejected = _apply_budget(
        valid,
        library,
        rejected,
        remaining_source_requests,
        remaining_llm_calls,
        remaining_deep_reads,
    )
    budget_hit = any(item.reason == "budget_exhausted" for item in rejected)
    stop_reason: StopReason | None = "budget_exhausted" if not affordable and budget_hit else None
    admitted, rejected, synthesized, stop_reason = _resolve_stop(
        spec,
        coverage,
        affordable,
        rejected,
        remaining_source_requests,
        remaining_llm_calls,
        stop_reason,
    )
    if max_actions_per_round < len(admitted):
        for action in admitted[max_actions_per_round:]:
            rejected.append(RejectedAction(action_id=action.action_id, reason="action_cap"))
        admitted = admitted[:max_actions_per_round]
    return AdmissionResult(
        actions=admitted,
        rejected=rejected,
        synthesized_from_gap=synthesized,
        stop_reason=stop_reason,
    )


def _structural_reason(
    spec: ResearchSpec,
    action: RoundAction,
    library: dict[UUID, PaperAdmission],
    citations: dict[str, int],
    max_citation_neighbors: int,
    max_search_calls: int,
) -> str | None:
    questions = {question.question_id for question in spec.questions}
    columns = {column.column_id for column in spec.columns}
    if any(question_id not in questions for question_id in action.question_ids):
        return "unknown_question"
    if any(column_id not in columns for column_id in action.column_ids):
        return "unknown_column"
    if any(provider not in spec.scope.enabled_sources for provider in action.providers):
        return "source_not_enabled"
    if action.kind == "search_works":
        if action.query is None or not action.query.strip():
            return "missing_query"
        if not action.providers:
            return "source_not_enabled"
        return None
    if action.kind == "expand_citations":
        return _citation_reason(action, library, citations, max_citation_neighbors)
    if action.kind == "read_fulltext":
        return _read_reason(action, library)
    if action.kind == "search_in_paper":
        return _in_paper_reason(action, library, max_search_calls)
    return None


def _citation_reason(
    action: RoundAction,
    library: dict[UUID, PaperAdmission],
    citations: dict[str, int],
    max_neighbors: int,
) -> str | None:
    if not action.paper_ids:
        return "paper_not_in_library"
    for paper_id in action.paper_ids:
        paper = library.get(paper_id)
        if paper is None:
            return "paper_not_in_library"
        if paper.status == "excluded":
            return "paper_excluded"
    if action.direction is None:
        return "missing_direction"
    requested = citations.get(action.action_id)
    if requested is not None and requested > max_neighbors:
        return "citation_cap"
    return None


def _read_reason(action: RoundAction, library: dict[UUID, PaperAdmission]) -> str | None:
    if not action.paper_ids:
        return "paper_not_in_library"
    for paper_id in action.paper_ids:
        paper = library.get(paper_id)
        if paper is None:
            return "paper_not_in_library"
        if paper.status == "excluded":
            return "paper_excluded"
        # 全文只能下载已纳入或本轮选中的论文。没有摘要本身不是不相关。
        if not paper.included and not paper.selected_this_round:
            return "not_included_or_selected"
        if paper.abstract_missing and paper.relevance is None:
            return None
        if paper.status != "pinned" and (paper.relevance is None or paper.relevance < 3):
            return "relevance_too_low"
    return None


def _in_paper_reason(
    action: RoundAction, library: dict[UUID, PaperAdmission], max_calls: int
) -> str | None:
    if not action.paper_ids or not action.column_ids:
        return "column_not_empty"
    for paper_id in action.paper_ids:
        paper = library.get(paper_id)
        if paper is None:
            return "paper_not_in_library"
        if paper.status == "excluded":
            return "paper_excluded"
        if not paper.has_document:
            return "missing_document"
        if paper.search_in_paper_calls >= max_calls:
            return "search_call_cap"
        if any(column_id not in paper.empty_required_column_ids for column_id in action.column_ids):
            return "column_not_empty"
    return None


def _apply_budget(
    actions: list[RoundAction],
    library: dict[UUID, PaperAdmission],
    rejected: list[RejectedAction],
    sources: int,
    llm_calls: int,
    deep_reads: int,
) -> tuple[list[RoundAction], list[RejectedAction]]:
    kept: list[RoundAction] = []
    for action in actions:
        source_cost, llm_cost, deep_cost = _cost(action, library)
        if deep_cost > deep_reads:
            rejected.append(RejectedAction(action_id=action.action_id, reason="deep_read_quota"))
            continue
        if source_cost > sources or llm_cost > llm_calls:
            rejected.append(RejectedAction(action_id=action.action_id, reason="budget_exhausted"))
            continue
        sources -= source_cost
        llm_calls -= llm_cost
        deep_reads -= deep_cost
        kept.append(action)
    return kept, rejected


def _cost(action: RoundAction, library: dict[UUID, PaperAdmission]) -> tuple[int, int, int]:
    if action.kind == "search_works":
        return len(action.providers), 0, 0
    if action.kind == "expand_citations":
        return 1, 0, 0
    if action.kind == "search_in_paper":
        return 0, 1, 0
    if action.kind == "read_fulltext":
        download = any(not library[paper_id].has_document for paper_id in action.paper_ids)
        count = len(action.paper_ids)
        return int(download), count, count
    return 0, 0, 0


def _resolve_stop(
    spec: ResearchSpec,
    coverage: CoverageReport,
    actions: list[RoundAction],
    rejected: list[RejectedAction],
    remaining_source_requests: int,
    remaining_llm_calls: int,
    stop_reason: StopReason | None,
) -> tuple[list[RoundAction], list[RejectedAction], RoundAction | None, StopReason | None]:
    stops = [action for action in actions if action.kind == "stop"]
    others = [action for action in actions if action.kind != "stop"]
    if not stops:
        return others, rejected, None, stop_reason
    can_research = remaining_source_requests >= 1 and bool(spec.scope.enabled_sources)
    can_research = can_research or remaining_llm_calls >= 1
    accept = (
        coverage.saturated
        or coverage.consecutive_saturated_rounds >= 2
        or not can_research
        or not coverage.unmet_question_ids
    )
    chosen = stops[0]
    if accept:
        for action in [*others, *stops[1:]]:
            rejected.append(RejectedAction(action_id=action.action_id, reason="stop_accepted"))
        return [chosen], rejected, None, stop_reason
    for action in stops:
        rejected.append(RejectedAction(action_id=action.action_id, reason="unmet_coverage"))
    if others:
        return others, rejected, None, stop_reason
    synthesized = _gap_search(spec, coverage)
    if (
        synthesized is not None
        and remaining_source_requests >= 1
        and bool(spec.scope.enabled_sources)
    ):
        return [synthesized], rejected, synthesized, stop_reason
    return [], rejected, None, "budget_exhausted"


def _gap_search(spec: ResearchSpec, coverage: CoverageReport) -> RoundAction | None:
    if not spec.scope.enabled_sources:
        return None
    columns = {column.column_id: column for column in spec.columns}
    questions = {question.question_id: question for question in spec.questions}
    for question_id in coverage.unmet_question_ids:
        target = next((item for item in spec.coverage if item.question_id == question_id), None)
        question = questions.get(question_id)
        if target is None or question is None:
            continue
        column = columns.get(target.required_column_ids[0])
        if column is None:
            continue
        terms = " ".join(question.search_terms_en)
        return RoundAction(
            action_id="gap-search",
            kind="search_works",
            question_ids=[question_id],
            column_ids=[column.column_id],
            rationale="synthesized_from_gap",
            query=f"{column.description_zh} {terms}".strip(),
            providers=[spec.scope.enabled_sources[0]],
        )
    return None
