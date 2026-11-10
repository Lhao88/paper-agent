from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
        },
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def get_test_settings(settings: Settings | None = None) -> Settings:
    original = settings or get_settings()
    name = original.db_name
    if not name.endswith("_test"):
        name += "_test"
    storage = (
        original.storage_root if original.app_env == "test" else original.storage_root / "test"
    )
    return original.model_copy(update={"app_env": "test", "db_name": name, "storage_root": storage})


async def assert_test_database(session: AsyncSession) -> None:
    database_name = await session.scalar(text("select current_database()"))
    if not isinstance(database_name, str) or not database_name.endswith("_test"):
        raise ValueError("refusing test operations on a business database")


@asynccontextmanager
async def test_session_scope(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
            ) as session:
                await assert_test_database(session)
                yield session
        finally:
            await transaction.rollback()
