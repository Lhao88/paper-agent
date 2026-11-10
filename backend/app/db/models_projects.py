from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Created, Identified

ACTIVE_STATUSES = ("queued", "running", "waiting_user", "interrupted")


class Project(Identified, Created, Base):
    __tablename__ = "projects"
    title: Mapped[str] = mapped_column(String(300))
    topic: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResearchPlan(Identified, Created, Base):
    __tablename__ = "research_plans"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(default=1)
    questions_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    scope_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    spec_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Run(Identified, Created, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        CheckConstraint(
            "status IN ('queued','running','waiting_user','interrupted',"
            "'completed','partial','failed','cancelled')",
            name="status",
        ),
        CheckConstraint(
            "used_calls>=0 AND reserved_calls>=0 AND used_tokens>=0 AND reserved_tokens>=0",
            name="nonnegative_budget",
        ),
        Index(
            "uq_project_active_run",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running','waiting_user','interrupted')"),
        ),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("research_plans.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", server_default="queued")
    stage: Mapped[str] = mapped_column(String(40), default="plan", server_default="plan")
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    config_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    progress_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    error_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    claim_token: Mapped[UUID | None]
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_elapsed_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    supplement_round: Mapped[int] = mapped_column(default=0, server_default="0")
    revision_round: Mapped[int] = mapped_column(default=0, server_default="0")
    retrieval_accepting: Mapped[bool] = mapped_column(default=False, server_default="false")
    used_source_requests: Mapped[int] = mapped_column(default=0, server_default="0")
    reserved_source_requests: Mapped[int] = mapped_column(default=0, server_default="0")
    used_calls: Mapped[int] = mapped_column(default=0, server_default="0")
    reserved_calls: Mapped[int] = mapped_column(default=0, server_default="0")
    used_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    reserved_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    max_calls: Mapped[int] = mapped_column(default=150, server_default="150")
    max_tokens: Mapped[int] = mapped_column(default=400000, server_default="400000")
