import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.prompts import json_text
from app.config import Settings
from app.errors import DomainError


@dataclass(frozen=True)
class Services:
    settings: Settings
    factory: async_sessionmaker[AsyncSession]


def hash_input(value: object) -> str:
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def validate_key(key: str) -> str:
    if not key.strip() or len(key) > 200:
        raise DomainError("INVALID_IDEMPOTENCY_KEY", "幂等键需为1到200个字符。")
    return key


def row_data(row: object) -> dict[str, object]:
    mapper = inspect(type(row))
    if mapper is None:
        raise TypeError("expected a mapped database row")
    result: dict[str, object] = {}
    for attr in mapper.column_attrs:
        value = getattr(row, attr.key)
        result[attr.key] = (
            str(value)
            if isinstance(value, UUID)
            else value.isoformat()
            if isinstance(value, datetime)
            else value
        )
    return result
