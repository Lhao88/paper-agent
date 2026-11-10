from alembic import context
from sqlalchemy import create_engine, pool

from app.config import Settings, get_settings
from app.db import Base

config = context.config
provided = config.attributes.get("settings")
settings = provided if isinstance(provided, Settings) else get_settings()


def include_name(name, type_, parent_names):
    # LangGraph owns its checkpoint tables; never autogenerate changes for those.
    return type_ != "table" or name in Base.metadata.tables


if context.is_offline_mode():
    context.configure(
        url=settings.database_url,
        target_metadata=Base.metadata,
        include_name=include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
