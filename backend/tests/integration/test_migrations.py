from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import migration_config
from app.db import Base
from app.db.session import get_test_settings


async def test_test_database_matches_migration_head_and_business_metadata(
    db_session: AsyncSession,
) -> None:
    connection = await db_session.connection()

    def compare(sync_connection):
        context = MigrationContext.configure(
            sync_connection,
            opts={
                "include_name": lambda name, type_, parents: (
                    type_ != "table" or name in Base.metadata.tables
                ),
            },
        )
        return context.get_current_revision(), compare_metadata(context, Base.metadata)

    revision, differences = await connection.run_sync(compare)
    head = ScriptDirectory.from_config(migration_config(get_test_settings())).get_current_head()
    assert revision == head
    assert differences == []
