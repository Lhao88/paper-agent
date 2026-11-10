import json
from typing import Literal

import httpx2
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config import Settings
from app.errors import DomainError
from app.llm.base import Message, RawModelResponse


class OpenAICompatibleTransport:
    def __init__(self, settings: Settings, http_client: httpx2.AsyncClient | None = None) -> None:
        if settings.llm_mode != "live":
            raise DomainError("LIVE_MODE_REQUIRED", "显式开启live模式后才能创建真实模型客户端。")
        self.settings = settings
        self.http_client = http_client

    async def generate[T: BaseModel](
        self,
        schema: type[T],
        messages: list[Message],
        profile: Literal["screen", "research"],
        max_output_tokens: int,
    ) -> RawModelResponse:
        settings = self.settings
        model_id = settings.llm_screen_model if profile == "screen" else settings.llm_research_model
        model = ChatOpenAI(
            model=model_id,
            api_key=settings.llm_api_key,
            base_url=str(settings.llm_base_url),
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            max_completion_tokens=max_output_tokens,
            http_async_client=self.http_client,
        )
        input_messages = [(message.role, message.content) for message in messages]
        if settings.llm_output_mode == "json_prompt":
            input_messages = [
                (
                    "system",
                    "Return only JSON matching this schema: "
                    + json.dumps(schema.model_json_schema()),
                ),
                *input_messages,
            ]
            raw = await model.ainvoke(input_messages)
            payload: object = raw.content
        else:
            structured = model.with_structured_output(
                schema,
                method=settings.llm_output_mode,
                include_raw=True,
            )
            result = await structured.ainvoke(input_messages)
            if not isinstance(result, dict) or not isinstance(result.get("raw"), AIMessage):
                raise DomainError("MODEL_RESPONSE_INVALID", "模型适配器返回了不支持的结构。")
            raw = result["raw"]
            parsed = result.get("parsed")
            payload = (
                parsed.model_dump(mode="json") if isinstance(parsed, BaseModel) else raw.content
            )
        usage = raw.usage_metadata
        metadata = raw.response_metadata
        return RawModelResponse(
            payload=payload,
            input_tokens=usage.get("input_tokens") if usage else None,
            output_tokens=usage.get("output_tokens") if usage else None,
            provider_request_id=raw.id,
            finish_reason=str(metadata.get("finish_reason", "stop")),
            refused=bool(raw.additional_kwargs.get("refusal")),
            model_snapshot={
                "model": model_id,
                "profile": profile,
                "output_mode": settings.llm_output_mode,
            },
        )
