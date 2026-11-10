from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import ModelCall, Run
from app.errors import DomainError


@dataclass(frozen=True)
class Reservation:
    call_id: UUID
    attempt: int
    reserved_tokens: int
    cached_output: dict[str, object] | None = None
    actual_tokens: int | None = None


class BudgetService:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def reserve_source_request(self, run_id: UUID, limit: int) -> None:
        async with self.factory.begin() as session:
            run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None or run.status not in ("queued", "running"):
                raise DomainError("RUN_NOT_EXECUTABLE", "研究当前不能检索。")
            if run.cancel_requested_at is not None:
                raise DomainError("RUN_CANCELLED", "已请求取消，停止派发来源请求。")
            frozen = run.config_snapshot.get("max_source_requests")
            if isinstance(frozen, int) and not isinstance(frozen, bool):
                limit = min(limit, frozen)
            if run.used_source_requests + run.reserved_source_requests >= limit:
                raise DomainError("BUDGET_EXHAUSTED", "论文来源请求预算不足。")
            # Count before dispatch, including failed requests and safe metadata retries.
            run.used_source_requests += 1

    async def reserve_call(
        self,
        run_id: UUID,
        operation_key: str,
        input_hash: str,
        estimated_tokens: int,
        max_attempts: int = 2,
    ) -> Reservation:
        if estimated_tokens <= 0:
            raise ValueError("estimated_tokens must be positive")
        key = f"{run_id}:{operation_key}"
        async with self.factory.begin() as session:
            run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None or run.status not in ("queued", "running"):
                raise DomainError("RUN_NOT_EXECUTABLE", "研究已停止或当前不允许模型调用。")
            if run.cancel_requested_at is not None:
                raise DomainError("RUN_CANCELLED", "已请求取消，停止派发模型请求。")
            previous = await session.scalar(
                select(ModelCall)
                .where(ModelCall.run_id == run_id, ModelCall.operation_key == key)
                .order_by(ModelCall.attempt.desc())
                .limit(1)
            )
            if previous is not None:
                if previous.input_hash != input_hash:
                    raise DomainError("OPERATION_INPUT_CONFLICT", "同一操作的输入发生变化。")
                if previous.output_json is not None:
                    return Reservation(
                        previous.id,
                        previous.attempt,
                        previous.reserved_tokens,
                        previous.output_json,
                        previous.actual_tokens,
                    )
                if previous.status == "unknown":
                    raise DomainError("MODEL_TIMEOUT_UNKNOWN", "已有调用状态未知，需先核对。")
                if previous.status in ("reserved", "sent"):
                    raise DomainError("CALL_IN_PROGRESS", "相同模型操作正在执行。")
            reusable = previous is not None and previous.status == "cancelled_before_send"
            attempt = (
                1 if previous is None else previous.attempt if reusable else previous.attempt + 1
            )
            unresolved = await session.scalar(
                select(ModelCall.id)
                .where(ModelCall.run_id == run_id, ModelCall.status == "unknown")
                .limit(1)
            )
            if unresolved is not None:
                raise DomainError(
                    "UNRESOLVED_MODEL_CALLS", "已有未知调用，先核对账本再派发新请求。"
                )
            if attempt > max_attempts:
                raise DomainError("MODEL_RETRY_LIMIT", "模型操作已达到重试上限。")
            if (
                run.used_calls + run.reserved_calls >= run.max_calls
                or run.used_tokens + run.reserved_tokens + estimated_tokens > run.max_tokens
            ):
                raise DomainError("BUDGET_EXHAUSTED", "剩余调用预算不足。")
            if reusable and previous is not None:
                call = previous
                call.status, call.reserved_tokens = "reserved", estimated_tokens
            else:
                call = ModelCall(
                    id=uuid4(),
                    run_id=run_id,
                    operation_key=key,
                    attempt=attempt,
                    reserved_tokens=estimated_tokens,
                    input_hash=input_hash,
                )
                session.add(call)
            run.reserved_calls += 1
            run.reserved_tokens += estimated_tokens
            return Reservation(call.id, attempt, estimated_tokens)

    async def _lock_call(self, session: AsyncSession, call_id: UUID) -> tuple[Run, ModelCall]:
        run_id = await session.scalar(select(ModelCall.run_id).where(ModelCall.id == call_id))
        if run_id is None:
            raise DomainError("CALL_NOT_FOUND", "调用记录不存在。")
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        call = await session.scalar(
            select(ModelCall).where(ModelCall.id == call_id).with_for_update()
        )
        if run is None or call is None:
            raise DomainError("CALL_NOT_FOUND", "调用记录不存在。")
        return run, call

    async def mark_sent(self, call_id: UUID) -> None:
        async with self.factory.begin() as session:
            run, call = await self._lock_call(session, call_id)
            if call.status == "reserved":
                run.reserved_calls -= 1
                run.used_calls += 1
                call.status = "sent"

    async def mark_unknown(self, call_id: UUID) -> None:
        async with self.factory.begin() as session:
            _, call = await self._lock_call(session, call_id)
            if call.status == "sent":
                call.status = "unknown"

    async def settle_call(
        self,
        call_id: UUID,
        usage: int | None,
        output: dict[str, object] | None,
        provider_request_id: str | None = None,
        model_snapshot: dict[str, object] | None = None,
    ) -> None:
        if usage is not None and usage < 0:
            raise ValueError("usage must be nonnegative or unknown")
        async with self.factory.begin() as session:
            run, call = await self._lock_call(session, call_id)
            if call.status not in ("sent", "unknown"):
                return
            if usage is not None:
                run.reserved_tokens -= call.reserved_tokens
                run.used_tokens += usage
            call.actual_tokens = usage
            call.output_json = output
            call.provider_request_id = provider_request_id
            call.model_snapshot = model_snapshot or {}
            call.status = (
                ("succeeded" if usage is not None else "usage_unknown")
                if (output is not None)
                else "failed"
            )
