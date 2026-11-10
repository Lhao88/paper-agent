from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Question(StrictModel):
    question_id: str
    text_zh: str
    search_terms_en: list[str]
    priority: Literal[1, 2, 3] = 2


class Scope(StrictModel):
    year_from: int | None = Field(default=None, ge=1800, le=2200)
    year_to: int | None = Field(default=None, ge=1800, le=2200)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    enabled_sources: list[str] = Field(default_factory=lambda: ["openalex"])

    @model_validator(mode="after")
    def validate_years(self) -> "Scope":
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must not exceed year_to")
        return self


class PlanRequest(StrictModel):
    topic: str = Field(min_length=1, max_length=2000)
    scope: Scope = Field(default_factory=Scope)


class PlanDraft(StrictModel):
    topic: str
    questions: list[Question] = Field(min_length=3, max_length=5)
    scope: Scope
    assumptions: list[str] = Field(default_factory=list)
    suggested_budgets: dict[str, int] = Field(default_factory=dict)


class ResearchPlan(PlanDraft):
    plan_id: UUID
    project_id: UUID
    version: int = Field(ge=1)
    budgets: dict[str, int] = Field(default_factory=dict)


class InclusionRule(StrictModel):
    rule_id: str
    polarity: Literal["include", "exclude"]
    text_zh: str = Field(min_length=1, max_length=300)


class ExtractionColumn(StrictModel):
    column_id: str
    question_id: str
    field: Literal["method", "dataset", "experimental_setup", "metric", "result", "limitation"]
    required: bool
    description_zh: str = Field(min_length=1, max_length=300)


class CoverageTarget(StrictModel):
    question_id: str
    min_included_papers: int = Field(default=3, ge=1, le=15)
    required_column_ids: list[str] = Field(min_length=1)


class SpecDraft(StrictModel):
    topic: str
    questions: list[Question] = Field(min_length=3, max_length=5)
    scope: Scope
    inclusion_rules: list[InclusionRule] = Field(min_length=1, max_length=12)
    columns: list[ExtractionColumn] = Field(min_length=1, max_length=12)
    coverage: list[CoverageTarget]
    assumptions: list[str] = Field(default_factory=list)


class ResearchSpec(SpecDraft):
    pass


class SearchQuery(StrictModel):
    query_id: str
    question_ids: list[str] = Field(min_length=1)
    provider: str
    terms: str = Field(min_length=1, max_length=1000)
    year_from: int | None = None
    year_to: int | None = None
    languages: list[str] = Field(default_factory=list)


class QueryPlan(StrictModel):
    queries: list[SearchQuery] = Field(min_length=1, max_length=20)
    scope: Scope | None = None


class SourceRecord(StrictModel):
    source_id: UUID | None = None
    provider: str
    provider_id: str
    version_label: str
    abstract: str | None = None
    landing_url: str | None = None
    pdf_url: str | None = None
    license: str | None = None
    raw_payload: dict[str, object] = Field(default_factory=dict)

    @property
    def source_key(self) -> str:
        return f"{self.provider}:{self.provider_id}:{self.version_label}"


class PaperRecord(StrictModel):
    paper_id: UUID = Field(default_factory=uuid4)
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    abstract_status: Literal["provided", "missing", "reconstruction_incomplete"] = "missing"
    abstract_source_key: str | None = None
    source_id: UUID | None = None
    sources: list[SourceRecord]


class SearchPage(StrictModel):
    records: list[PaperRecord]
    next_cursor: str | None = None
    has_more: bool = False
    raw_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class RetrievalResult(StrictModel):
    records: list[PaperRecord]
    warnings: list[str]
    filtered_out: list[dict[str, str]] = Field(default_factory=list)


class ScreenDecision(StrEnum):
    PRIORITY = "priority"
    CANDIDATE = "candidate"
    EXCLUDE = "exclude"
    INSUFFICIENT = "insufficient_info"


class ScreenOutput(StrictModel):
    summary_zh: str
    matched_question_ids: list[str]
    relevance: int | None = Field(ge=0, le=4)
    decision: ScreenDecision
    reason: str
    missing_information: list[str]


class ScreeningCard(ScreenOutput):
    paper_id: UUID
    material_basis: Literal["abstract", "metadata_only"]


class PreselectionResult(StrictModel):
    selected_ids: list[UUID]
    deferred_ids: list[UUID]
    missing_abstract_ids: list[UUID]
    ranking_details: dict[str, dict[str, float]] = Field(default_factory=dict)
    limit: int = Field(ge=1)


class SelectionResult(StrictModel):
    selected_ids: list[UUID]
    reasons_by_paper: dict[str, str]
    covered_question_ids: list[str]
    uncovered_question_ids: list[str]
    deferred_ids: list[UUID]
    deferred_reasons: dict[str, str] = Field(default_factory=dict)
    score_details: dict[str, dict[str, float]] = Field(default_factory=dict)
    selection_version: str = "coverage-v1"


class ExtractionCandidate(StrictModel):
    field_name: Literal[
        "research_question",
        "method",
        "dataset",
        "experimental_setup",
        "metric",
        "result",
        "limitation",
    ]
    value_zh: str
    chunk_id: UUID
    quote: str
    statement_type: Literal["reported_fact", "author_interpretation"]


class ClaimBlock(StrictModel):
    text: str
    evidence_ids: list[UUID]
    kind: Literal["literature_claim", "synthesis", "transition", "hypothesis"]


class SectionOutput(StrictModel):
    title: str
    blocks: list[ClaimBlock]
    unresolved_questions: list[str]


class FollowupDecision(StrictModel):
    action: Literal["retrieve_more", "read_more", "finish", "needs_input"]
    question_ids: list[str]
    paper_ids: list[UUID]
    rationale: str


class RoundAction(StrictModel):
    action_id: str
    kind: Literal["search_works", "expand_citations", "read_fulltext", "search_in_paper", "stop"]
    question_ids: list[str] = Field(min_length=1)
    rationale: str
    query: str | None = None
    providers: list[str] = Field(default_factory=list)
    paper_ids: list[UUID] = Field(default_factory=list)
    direction: Literal["references", "cited_by"] | None = None
    column_ids: list[str] = Field(default_factory=list)


class RoundPlan(StrictModel):
    actions: list[RoundAction] = Field(min_length=1, max_length=6)


class CoverageCell(StrictModel):
    question_id: str
    column_id: str
    filled_papers: int
    required: bool


class CoverageReport(StrictModel):
    round_index: int
    questions: list[dict[str, int]]
    cells: list[CoverageCell]
    unmet_question_ids: list[str]
    remaining_source_requests: int
    remaining_llm_calls: int
    remaining_deep_reads: int
    new_relevant_papers_last_round: int
    consecutive_saturated_rounds: int
    corpus_limits: list[str]
    saturated: bool


class NotebookPage(StrictModel):
    round_index: int
    executed_action_ids: list[str]
    rejected_actions: list[dict[str, str]]
    new_paper_ids: list[UUID]
    filled_column_ids: list[str]
    open_gaps: list[str]
    queries: list[str] = Field(default_factory=list)
    index_mode: Literal["hybrid", "bm25"]


class ClaimRecord(StrictModel):
    claim_id: UUID
    paper_id: UUID
    question_id: str
    column_id: str
    evidence_id: UUID
    polarity: Literal["support", "contradict"]
    value_zh: str


class WordBox(StrictModel):
    text: str
    x0: float
    top: float
    x1: float
    bottom: float


class ParsedPage(StrictModel):
    page_number: int = Field(ge=1)
    text: str
    words: list[WordBox]


class ParsedDocument(StrictModel):
    document_id: UUID
    parser_version: str
    pages: list[ParsedPage]
    warnings: list[str]


class ChunkRecord(StrictModel):
    chunk_id: UUID
    document_id: UUID
    page_number: int = Field(ge=1)
    text: str
    text_sha256: str
    section_hint: str | None = None
    words: list[WordBox] = Field(default_factory=list)


class ChunkSelection(StrictModel):
    document_id: UUID
    chunk_ids: list[UUID]
    covered_sections: list[str]
    omitted_sections: list[str]
    reading_scope: Literal["full_text_complete", "full_text_targeted"]
    total_chunks: int = 0
    omitted_chunk_count: int = 0


class EvidenceRecord(StrictModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    paper_id: UUID
    basis: Literal["full_text", "abstract"]
    source_id: UUID | None = None
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    quote: str
    quote_start: int
    quote_end: int
    page_number: int | None = None
    statement_type: Literal["reported_fact", "author_interpretation"]


class ExtractionOutput(StrictModel):
    candidates: list[ExtractionCandidate]


class ReadingFact(StrictModel):
    value_zh: str
    evidence_ids: list[UUID]
    statement_type: Literal["reported_fact", "author_interpretation"]


class ReadingCard(StrictModel):
    paper_id: UUID
    document_id: UUID | None = None
    reading_scope: Literal["full_text_complete", "full_text_targeted", "abstract_only"]
    examined_chunk_ids: list[UUID]
    fields: dict[str, list[ReadingFact]]
    missing_fields: dict[str, str]
    warnings: list[str]


class DocumentResult(StrictModel):
    paper_id: UUID
    document_id: UUID | None = None
    storage_key: str | None = None
    source_id: UUID | None = None
    status: Literal["downloaded", "full_text_unavailable"]
    warnings: list[str] = Field(default_factory=list)
