from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings


async def test_postgres_schema_rejects_two_active_runs_for_one_project() -> None:
    settings = Settings()
    test_name = (
        settings.db_name if settings.db_name.endswith("_test") else settings.db_name + "_test"
    )
    engine = create_async_engine(settings.database_url.set(database=test_name))
    project_id = uuid4()
    try:
        async with engine.begin() as connection:
            actual_db = await connection.scalar(text("select current_database()"))
            assert actual_db == "research_test"
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    text(
                        "insert into projects (id,title,topic,created_at,updated_at) "
                        "values (:id,'fixture','fixture',now(),now())"
                    ),
                    {"id": project_id},
                )
                for index in range(2):
                    savepoint = await connection.begin_nested()
                    query = text(
                        "insert into runs (id,project_id,status,idempotency_key,request_hash,"
                        "input_snapshot,config_snapshot,created_at,available_at) "
                        "values (:id,:pid,'queued',:key,'hash','{}','{}',now(),now())"
                    )
                    if index == 1:
                        with pytest.raises(IntegrityError):
                            await connection.execute(
                                query, {"id": uuid4(), "pid": project_id, "key": str(uuid4())}
                            )
                    else:
                        await connection.execute(
                            query, {"id": uuid4(), "pid": project_id, "key": str(uuid4())}
                        )
                    await savepoint.rollback() if index else await savepoint.commit()
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
