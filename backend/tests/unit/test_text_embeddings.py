from pathlib import Path

from sqlalchemy import REAL
from sqlalchemy.dialects.postgresql import ARRAY

from app.config import PROJECT_ROOT
from app.db import TextEmbedding


def test_text_embedding_stores_postgres_real_array() -> None:
    vector = TextEmbedding.__table__.c.vector.type
    assert isinstance(vector, ARRAY)
    assert isinstance(vector.item_type, REAL)
    assert "pgvector" not in type(vector).__module__
    constraint = next(
        item
        for item in TextEmbedding.__table__.constraints
        if getattr(item, "name", "") == "text_embedding_identity"
    )
    assert {column.name for column in constraint.columns} == {
        "project_id",
        "owner_type",
        "owner_id",
        "model_id",
    }


def test_text_embedding_migration_does_not_install_pgvector() -> None:
    versions = PROJECT_ROOT / "backend" / "migrations" / "versions"
    texts = [path.read_text(encoding="utf-8").lower() for path in Path(versions).glob("*.py")]
    embedding = [text for text in texts if "text_embeddings" in text]
    assert len(embedding) == 1
    migration = embedding[0]
    assert "array" in migration and "real" in migration
    assert "pgvector" not in migration
    assert "create extension" not in migration
