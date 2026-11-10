from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str
    fixture_key: str | None = None
    fixture_bindings: dict[str, str] | None = None


@dataclass(frozen=True)
class CallContext:
    run_id: UUID
    operation_key: str


@dataclass(frozen=True)
class RawModelResponse:
    payload: object
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_request_id: str | None = None
    finish_reason: str = "stop"
    refused: bool = False
    model_snapshot: dict[str, object] | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ModelResult[T: BaseModel]:
    parsed: T
    provider_request_id: str | None
    total_tokens: int | None
    cached: bool = False


class ModelTransport(Protocol):
    async def generate[T: BaseModel](
        self,
        schema: type[T],
        messages: list[Message],
        profile: Literal["screen", "research"],
        max_output_tokens: int,
    ) -> RawModelResponse: ...
