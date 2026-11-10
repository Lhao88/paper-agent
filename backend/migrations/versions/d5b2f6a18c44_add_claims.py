"""Store project-scoped claims that point at existing evidence."""

import sqlalchemy as sa
from alembic import op

revision = "d5b2f6a18c44"
down_revision = "a4e8c1b07d33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.String(length=80), nullable=False),
        sa.Column("column_id", sa.String(length=80), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("polarity", sa.String(length=20), nullable=False),
        sa.Column("value_zh", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "polarity IN ('support', 'contradict')", name=op.f("ck_claims_polarity")
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["evidence.id"], name=op.f("fk_claims_evidence_id_evidence")
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], name=op.f("fk_claims_paper_id_papers")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_claims_project_id_projects")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_claims_run_id_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
        sa.UniqueConstraint(
            "project_id",
            "paper_id",
            "column_id",
            "evidence_id",
            "polarity",
            name="claim_identity",
        ),
    )
    op.create_index(op.f("ix_claims_evidence_id"), "claims", ["evidence_id"], unique=False)
    op.create_index(op.f("ix_claims_paper_id"), "claims", ["paper_id"], unique=False)
    op.create_index(op.f("ix_claims_project_id"), "claims", ["project_id"], unique=False)
    op.create_index(op.f("ix_claims_run_id"), "claims", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_claims_run_id"), table_name="claims")
    op.drop_index(op.f("ix_claims_project_id"), table_name="claims")
    op.drop_index(op.f("ix_claims_paper_id"), table_name="claims")
    op.drop_index(op.f("ix_claims_evidence_id"), table_name="claims")
    op.drop_table("claims")
