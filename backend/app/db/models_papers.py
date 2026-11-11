from uuid import UUID

from sqlalchemy import REAL, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Created, Identified


class Paper(Identified, Created, Base):
    __tablename__ = "papers"
    title: Mapped[str] = mapped_column(Text)
    canonical_doi: Mapped[str | None] = mapped_column(String(400), unique=True)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    year: Mapped[int | None]
    authors_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    work_family_id: Mapped[UUID | None]


class PaperSource(Identified, Created, Base):
    __tablename__ = "paper_sources"
    __table_args__ = (UniqueConstraint("provider", "provider_id", "version_label"),)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), index=True)
    owner_project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    provider_id: Mapped[str] = mapped_column(Text)
    version_label: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    abstract_text: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class ProjectPaper(Created, Base):
    __tablename__ = "project_papers"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), primary_key=True, index=True)
    added_by: Mapped[str] = mapped_column(String(30), default="retrieval")
    user_decision: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(default=1)


class PaperNeighbor(Created, Base):
    __tablename__ = "paper_neighbors"
    __table_args__ = (
        CheckConstraint("direction IN ('references', 'cited_by')", name="direction"),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    from_paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    to_paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    direction: Mapped[str] = mapped_column(String(20), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), primary_key=True)


class TextEmbedding(Identified, Created, Base):
    """摘要或分块向量。只存 PostgreSQL REAL[]，不使用 pgvector。"""

    __tablename__ = "text_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "owner_type",
            "owner_id",
            "model_id",
            name="text_embedding_identity",
        ),
        CheckConstraint("owner_type IN ('abstract', 'chunk')", name="owner_type"),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    owner_type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[UUID]
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), index=True)
    dimensions: Mapped[int]
    vector: Mapped[list[float]] = mapped_column(ARRAY(REAL()))
    model_id: Mapped[str] = mapped_column(String(200))


class Document(Identified, Created, Base):
    __tablename__ = "documents"
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), index=True)
    owner_project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("paper_sources.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(100), default="application/pdf")
    page_count: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(40), default="downloaded")
    parser_version: Mapped[str | None] = mapped_column(String(100))
    parse_warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    license_info: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class Chunk(Identified, Created, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", "text_sha256"),
        CheckConstraint("page_number>=1", name="positive_page"),
    )
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int]
    section_hint: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    word_boxes_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
