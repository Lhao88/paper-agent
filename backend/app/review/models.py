from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.contracts import (
    ClaimBlock,
    EvidenceRecord,
    ReadingCard,
    SectionOutput,
    StrictModel,
)


class QuestionAnalysis(StrictModel):
    question_id: str
    findings: str
    evidence_ids: list[UUID]
    agreements: list[str]
    disagreements: list[str]
    gaps: list[str]


class SectionPlan(StrictModel):
    section_id: str
    title: str
    goal: str
    question_ids: list[str]
    evidence_ids: list[UUID]


class SynthesisOutput(StrictModel):
    questions: list[QuestionAnalysis]
    outline: list[SectionPlan] = Field(min_length=1, max_length=10)


class ComparisonRow(StrictModel):
    paper_id: UUID
    reading_scope: str
    fields: dict[str, list[str]]
    evidence_ids: list[UUID]
    comparability: str = "未经实验条件一致性人工核验，不据此进行数值排名。"


class SynthesisArtifact(SynthesisOutput):
    comparison: list[ComparisonRow]
    warnings: list[str]


class ReviewSection(SectionOutput):
    section_id: str


class StoredClaim(ClaimBlock):
    block_id: UUID
    citation_numbers: list[int]


class StoredSection(StrictModel):
    section_id: str
    title: str
    blocks: list[StoredClaim]
    unresolved_questions: list[str]


class Reference(StrictModel):
    paper_id: UUID
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    source_urls: list[str]
    number: int = 0


class ReviewDocument(StrictModel):
    topic: str
    generated_at: datetime
    sections: list[StoredSection]
    evidence: list[EvidenceRecord]
    references: list[Reference]
    limitations: list[str]


class CheckIssue(StrictModel):
    block_id: UUID
    message: str
    suggestion: str
    evidence_ids: list[UUID]
    needs_human_check: bool = True


class SelfCheckOutput(StrictModel):
    issues: list[CheckIssue]


class ValidationReport(StrictModel):
    structural_valid: bool
    human_verified: bool = False
    semantic_status: Literal["needs_human_check"] = "needs_human_check"
    pending_block_ids: list[UUID]
    issues: list[CheckIssue]
    revision_round: int = 0


class EvidenceBundle(StrictModel):
    evidence: list[EvidenceRecord]
    references: list[Reference]
    cards: list[ReadingCard]


class ReviewBundle(StrictModel):
    synthesis_artifact_id: UUID | None
    outline_artifact_id: UUID | None
    review_artifact_id: UUID
    validation_artifact_id: UUID
    review: ReviewDocument
    validation: ValidationReport
