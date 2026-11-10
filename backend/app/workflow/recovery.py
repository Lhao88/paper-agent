from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import ModelCall, Run, RunEvent
from app.errors import DomainError


async def recover_run(
    factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    expected_claim_token: UUID | None,
    old_worker_stopped: bool,
) -> None:
    if not old_worker_stopped:
        raise DomainError("WORKER_STOP_NOT_CONFIRMED", "须确认旧worker进程已退出后才能恢复。")
    async with factory.begin() as session:
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise DomainError("RUN_NOT_FOUND", "研究不存在。")
        if run.claim_token != expected_claim_token or run.status not in {
            "interrupted",
            "running",
            "failed",
            "partial",
        }:
            raise DomainError("VERSION_CONFLICT", "恢复条件或运行归属已改变。")
        calls = list(
            await session.scalars(
                select(ModelCall).where(
                    ModelCall.run_id == run_id,
                    ModelCall.status.in_(["unknown", "sent", "reserved"]),
                )
            )
        )
        unresolved = []
        for call in calls:
            if call.status == "reserved":
                # The gateway commits mark_sent before contacting the transport.
                # After confirmed worker death this reservation is known unbilled.
                run.reserved_calls -= 1
                run.reserved_tokens -= call.reserved_tokens
                call.status = "cancelled_before_send"
            else:
                if call.status == "sent":
                    call.status = "unknown"
                unresolved.append(call)
        if unresolved:
            run.status = "interrupted"
            run.error_json = {
                "code": "UNRESOLVED_MODEL_CALLS",
                "call_ids": [str(call.id) for call in unresolved],
            }
        else:
            run.status = "queued"
            run.available_at = datetime.now(UTC)
            run.error_json = None
        run.worker_id = run.claim_token = run.lease_until = None
        session.add(
            RunEvent(run_id=run_id, event_type="recovery", payload_json={"status": run.status})
        )
