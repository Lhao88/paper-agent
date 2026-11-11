"""Store in-project embeddings as a PostgreSQL REAL[] column."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4a8e2b91d07"
down_revision = "e7c3a9d14b21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "text_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", postgresql.ARRAY(sa.REAL()), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "owner_type IN ('abstract', 'chunk')",
            name=op.f("ck_text_embeddings_owner_type"),
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], name=op.f("fk_text_embeddings_paper_id_papers")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_text_embeddings_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_text_embeddings")),
        sa.UniqueConstraint(
            "project_id",
            "owner_type",
            "owner_id",
            "model_id",
            name="text_embedding_identity",
        ),
    )
    op.create_index(
        op.f("ix_text_embeddings_paper_id"), "text_embeddings", ["paper_id"], unique=False
    )
    op.create_index(
        op.f("ix_text_embeddings_project_id"),
        "text_embeddings",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_text_embeddings_project_id"), table_name="text_embeddings")
    op.drop_index(op.f("ix_text_embeddings_paper_id"), table_name="text_embeddings")
    op.drop_table("text_embeddings")
