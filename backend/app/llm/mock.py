import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.errors import DomainError
from app.llm.base import Message, RawModelResponse


class MockModelTransport:
    """Fixture responses are keyed by schema name; missing fixtures fail explicitly."""

    def __init__(self, fixture_directory: Path) -> None:
        self.fixture_directory = fixture_directory.resolve()

    async def generate[T: BaseModel](
        self,
        schema: type[T],
        messages: list[Message],
        profile: Literal["screen", "research"],
        max_output_tokens: int,
    ) -> RawModelResponse:
        fixture_key = next((m.fixture_key for m in reversed(messages) if m.fixture_key), None)
        if fixture_key is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", fixture_key):
            raise DomainError("MOCK_FIXTURE_INVALID_KEY", "模拟资料标识格式无效。")
        suffix = f"-{fixture_key}" if fixture_key else ""
        path = self.fixture_directory / f"{schema.__name__}{suffix}.json"
        if not path.is_file():
            raise DomainError("MOCK_FIXTURE_NOT_FOUND", f"没有为{schema.__name__}定义模拟响应。")
        serialized = path.read_text(encoding="utf-8")
        bindings = (
            next((m.fixture_bindings for m in reversed(messages) if m.fixture_bindings), {}) or {}
        )
        for name, value in bindings.items():
            serialized = serialized.replace(json.dumps("$" + name), json.dumps(value))
        payload: object = json.loads(serialized)
        return RawModelResponse(
            payload,
            input_tokens=10,
            output_tokens=10,
            model_snapshot={"mode": "mock", "profile": profile},
        )
