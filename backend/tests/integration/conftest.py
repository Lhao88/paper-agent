from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import create_engine, get_test_settings, test_session_scope


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_engine(get_test_settings())
    try:
        async with test_session_scope(engine) as session:
            yield session
    finally:
        await engine.dispose()
