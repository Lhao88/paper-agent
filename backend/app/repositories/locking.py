import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_operation(session: AsyncSession, key: str) -> None:
    lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
    await session.execute(text("select pg_advisory_xact_lock(:key)"), {"key": lock_id})
