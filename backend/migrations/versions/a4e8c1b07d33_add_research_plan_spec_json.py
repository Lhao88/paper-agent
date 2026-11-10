"""Add nullable research spec payload to research plans."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a4e8c1b07d33"
down_revision = "c91de0234a01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_plans",
        sa.Column("spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_plans", "spec_json")
