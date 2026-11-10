from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Created, Identified


class Task(Identified, Created, Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("run_id", "operation", "client_request_key"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(80))
    paper_id: Mapped[UUID | None] = mapped_column(ForeignKey("papers.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    attempt: Mapped[int] = mapped_column(default=1)
    input_hash: Mapped[str] = mapped_column(String(64))
    client_request_key: Mapped[str | None] = mapped_column(String(200))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    input_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    output_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    output_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"), index=True)
    error_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelCall(Identified, Created, Base):
    __tablename__ = "model_calls"
    __table_args__ = (UniqueConstraint("operation_key", "attempt"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    operation_key: Mapped[str] = mapped_column(String(300))
    attempt: Mapped[int]
    status: Mapped[str] = mapped_column(String(40), default="reserved")
    reserved_tokens: Mapped[int]
    input_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    output_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    model_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    actual_tokens: Mapped[int | None]
    reserved_cost: Mapped[int | None] = mapped_column(BigInteger)
    actual_cost: Mapped[int | None] = mapped_column(BigInteger)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    result_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"), index=True)


class RunEvent(Created, Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB)
