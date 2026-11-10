import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.errors import DomainError
from app.llm.base import CallContext, Message, ModelResult, ModelTransport
from app.llm.budget import BudgetService
from app.llm.single_actor import with_shared_memory


class ModelGateway:
    def __init__(
        self, budget: BudgetService, transport: ModelTransport, settings: Settings
    ) -> None:
        self.budget = budget
        self.transport = transport
        self.settings = settings

    async def generate[T: BaseModel](
        self,
        schema: type[T],
        messages: list[Message],
        profile: Literal["screen", "research"],
        call_context: CallContext,
    ) -> ModelResult[T]:
        if self.settings.research_strategy == "B0":
            messages = await with_shared_memory(messages, call_context, self.budget)
        original_input = json.dumps(
            {
                "schema": schema.model_json_schema(),
                "messages": [asdict(m) for m in messages],
                "profile": profile,
                "model": self.settings.llm_screen_model
                if profile == "screen"
                else (self.settings.llm_research_model),
                "output_mode": self.settings.llm_output_mode,
                "output_limit": self.settings.llm_screen_max_output_tokens
                if profile == "screen"
                else (self.settings.llm_research_max_output_tokens),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        input_hash = hashlib.sha256(original_input.encode()).hexdigest()
        if len(original_input.encode()) > self.settings.llm_max_input_bytes:
            raise DomainError("MODEL_CONTEXT_LIMIT", "本次输入超过上下文上限，请分批处理。")
        output_limit = (
            self.settings.llm_screen_max_output_tokens
            if profile == "screen"
            else (self.settings.llm_research_max_output_tokens)
        )
        # Deliberately conservative byte-based estimate; actual reported usage settles it.
        estimate = len(original_input.encode()) + output_limit + 512
        request_messages = list(messages)
        max_attempts = self.settings.max_model_retries + 1
        for _ in range(max_attempts):
            reservation = await self.budget.reserve_call(
                call_context.run_id, call_context.operation_key, input_hash, estimate, max_attempts
            )
            if reservation.cached_output is not None:
                parsed = schema.model_validate_json(
                    json.dumps(reservation.cached_output), strict=True
                )
                return ModelResult(parsed, None, reservation.actual_tokens, cached=True)
            await self.budget.mark_sent(reservation.call_id)
            try:
                response = await self.transport.generate(
                    schema, request_messages, profile, output_limit
                )
            except asyncio.CancelledError:
                await asyncio.shield(self.budget.mark_unknown(reservation.call_id))
                raise
            except DomainError as exc:
                if self.settings.llm_mode == "mock" and exc.code.startswith("MOCK_"):
                    await self.budget.settle_call(reservation.call_id, 0, None)
                    raise
                await self.budget.mark_unknown(reservation.call_id)
                raise DomainError(
                    "MODEL_TIMEOUT_UNKNOWN", "模型请求结果未知，请先核对调用记录。"
                ) from exc
            except Exception as exc:
                await self.budget.mark_unknown(reservation.call_id)
                raise DomainError(
                    "MODEL_TIMEOUT_UNKNOWN", "模型请求结果未知，请先核对调用记录。"
                ) from exc
            if response.refused or response.finish_reason in ("length", "max_tokens"):
                await self.budget.settle_call(
                    reservation.call_id,
                    response.total_tokens,
                    None,
                    response.provider_request_id,
                    response.model_snapshot,
                )
                code = "MODEL_REFUSED" if response.refused else "MODEL_TRUNCATED"
                raise DomainError(code, "模型拒绝回答或输出被截断。")
            try:
                payload = response.payload
                serialized = payload if isinstance(payload, str) else json.dumps(payload)
                parsed = schema.model_validate_json(serialized, strict=True)
            except (ValidationError, TypeError, ValueError):
                await self.budget.settle_call(
                    reservation.call_id,
                    response.total_tokens,
                    None,
                    response.provider_request_id,
                    response.model_snapshot,
                )
                if reservation.attempt >= max_attempts:
                    raise DomainError("MODEL_SCHEMA_INVALID", "模型输出未满足资料契约。") from None
                request_messages = [
                    *messages,
                    Message(
                        "user", "上次输出未满足指定schema。请仅返回匹配schema的JSON，不要补充解释。"
                    ),
                ]
                continue
            await self.budget.settle_call(
                reservation.call_id,
                response.total_tokens,
                parsed.model_dump(mode="json"),
                response.provider_request_id,
                response.model_snapshot,
            )
            return ModelResult(parsed, response.provider_request_id, response.total_tokens)
        raise DomainError("MODEL_RETRY_LIMIT", "模型操作已达到重试上限。")
