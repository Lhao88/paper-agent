"""Record one-hop citation neighbors between papers already identified in a project."""

import sqlalchemy as sa
from alembic import op

revision = "e7c3a9d14b21"
down_revision = "d5b2f6a18c44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_neighbors",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("from_paper_id", sa.Uuid(), nullable=False),
        sa.Column("to_paper_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('references', 'cited_by')",
            name=op.f("ck_paper_neighbors_direction"),
        ),
        sa.ForeignKeyConstraint(
            ["from_paper_id"], ["papers.id"], name=op.f("fk_paper_neighbors_from_paper_id_papers")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_paper_neighbors_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["to_paper_id"], ["papers.id"], name=op.f("fk_paper_neighbors_to_paper_id_papers")
        ),
        sa.PrimaryKeyConstraint(
            "project_id",
            "from_paper_id",
            "to_paper_id",
            "direction",
            "provider",
            name=op.f("pk_paper_neighbors"),
        ),
    )


def downgrade() -> None:
    op.drop_table("paper_neighbors")
