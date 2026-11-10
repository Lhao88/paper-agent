"""Scope uploaded source snapshots and documents to their owning project."""
from alembic import op
import sqlalchemy as sa

revision = "c91de0234a01"
down_revision = "e08391ce4f5b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("paper_sources", "documents"):
        op.add_column(table, sa.Column("owner_project_id", sa.UUID(), nullable=True))
        op.create_foreign_key(f"fk_{table}_owner_project_id_projects", table, "projects", ["owner_project_id"], ["id"])
        op.create_index(f"ix_{table}_owner_project_id", table, ["owner_project_id"])


def downgrade() -> None:
    for table in ("documents", "paper_sources"):
        op.drop_index(f"ix_{table}_owner_project_id", table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_owner_project_id_projects"), table, type_="foreignkey")
        op.drop_column(table, "owner_project_id")
