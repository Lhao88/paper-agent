from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Created, Identified


class Evidence(Identified, Created, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "(basis='abstract' AND source_id IS NOT NULL AND document_id IS NULL "
            "AND chunk_id IS NULL AND page_number IS NULL) OR "
            "(basis='full_text' AND document_id IS NOT NULL AND chunk_id IS NOT NULL "
            "AND page_number IS NOT NULL AND page_number>=1)",
            name="basis_location",
        ),
        CheckConstraint("quote_start>=0 AND quote_end>quote_start", name="quote_span"),
    )
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), index=True)
    basis: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("paper_sources.id"), index=True)
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_id: Mapped[UUID | None] = mapped_column(ForeignKey("chunks.id"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    quote_start: Mapped[int]
    quote_end: Mapped[int]
    page_number: Mapped[int | None]
    statement_type: Mapped[str] = mapped_column(String(40))


class Claim(Identified, Created, Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "paper_id", "column_id", "evidence_id", "polarity", name="claim_identity"
        ),
        CheckConstraint("polarity IN ('support', 'contradict')", name="polarity"),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), index=True)
    question_id: Mapped[str] = mapped_column(String(80))
    column_id: Mapped[str] = mapped_column(String(80))
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id"), index=True)
    polarity: Mapped[str] = mapped_column(String(20))
    value_zh: Mapped[str] = mapped_column(Text)


class Artifact(Identified, Created, Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("run_id", "operation_key"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    paper_id: Mapped[UUID | None] = mapped_column(ForeignKey("papers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    operation_key: Mapped[str] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(default=1)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64))
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"), index=True)
