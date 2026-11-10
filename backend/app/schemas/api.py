from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.review.models import ReviewDocument, ValidationReport
from app.schemas.contracts import (
    EvidenceRecord,
    NotebookPage,
    ReadingCard,
    ResearchPlan,
    ResearchSpec,
    ScreeningCard,
    StrictModel,
)


class ProjectInput(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(min_length=1, max_length=2000)


class ProjectView(BaseModel):
    id: UUID
    title: str
    topic: str
    created_at: datetime
    updated_at: datetime


class RunView(BaseModel):
    id: UUID
    project_id: UUID
    plan_id: UUID | None
    status: str
    stage: str
    version: int
    used_calls: int
    reserved_calls: int
    used_tokens: int
    reserved_tokens: int
    max_calls: int
    max_tokens: int
    used_source_requests: int
    active_elapsed_seconds: float
    error_json: dict[str, object] | None
    config_snapshot: dict[str, object]
    progress_json: dict[str, object]
    unknown_calls: int = 0
    suspected_interruption: bool = False
    counts: dict[str, int] = Field(default_factory=dict)
    task: dict[str, object] | None = None
    round_index: int = 0
    unmet_question_ids: list[str] = Field(default_factory=list)
    stop_reason: str = ""
    created_at: datetime


class PlanView(BaseModel):
    run_version: int
    status: str
    plan: ResearchPlan
    spec: ResearchSpec | None = None


class NotebookView(BaseModel):
    pages: list[NotebookPage]
    unmet_question_ids: list[str] = Field(default_factory=list)


class ClaimView(StrictModel):
    polarity: Literal["support", "contradict"]
    question_id: str
    column_id: str
    value_zh: str


class ProjectPage(BaseModel):
    items: list[ProjectView]
    next_cursor: str | None


class ProjectDetails(ProjectView):
    runs: list[RunView]


class SelectionView(BaseModel):
    project_id: UUID
    paper_id: UUID
    user_decision: str | None
    version: int
    added_by: str


class PaperView(BaseModel):
    id: UUID
    title: str
    authors_json: list[str]
    year: int | None
    canonical_doi: str | None
    selection: SelectionView


class SourceView(BaseModel):
    id: UUID
    provider: str
    provider_id: str
    version_label: str
    abstract_text: str | None
    metadata_json: dict[str, object]


class DocumentView(BaseModel):
    id: UUID
    paper_id: UUID
    status: str
    page_count: int | None


class PaperDetailsView(PaperView):
    sources: list[SourceView]
    screen_cards: list[ScreeningCard]
    reading_cards: list[ReadingCard]
    documents: list[DocumentView]


class PaperPage(BaseModel):
    items: list[PaperView]
    next_cursor: str | None


class ReviewListItem(BaseModel):
    id: UUID
    version: int
    origin: str
    created_at: datetime
    supersedes_id: UUID | None


class ReviewView(BaseModel):
    id: UUID
    version: int
    origin: str
    review: ReviewDocument
    validation: ValidationReport


class EvidenceView(EvidenceRecord):
    reading_scope: str
    human_verified: bool = False
    claims: list[ClaimView] = Field(default_factory=list)


class SelectionInput(StrictModel):
    expected_version: int = Field(ge=1)
    user_decision: str | None = None


class EditInput(StrictModel):
    base_version: int = Field(ge=1)
    edited_blocks: dict[UUID, str]


class ResumeInput(StrictModel):
    expected_claim_token: UUID | None = None
    old_worker_stopped: bool
    reason: str = Field(min_length=1, max_length=1000)


class RetryInput(StrictModel):
    task_ids: list[UUID] = Field(min_length=1, max_length=100)
    expected_run_version: int = Field(ge=1)
    old_worker_stopped: bool
