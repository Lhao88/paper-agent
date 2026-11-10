"""Require a non-null page for full-text evidence (CHECK must reject SQL NULL)."""

from alembic import op

revision = "8f12be0c8b01"
down_revision = "7d7d2ba6076c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_evidence_basis_location"), "evidence", type_="check")
    op.create_check_constraint(
        "basis_location",
        "evidence",
        "(basis='abstract' AND source_id IS NOT NULL AND document_id IS NULL "
        "AND chunk_id IS NULL AND page_number IS NULL) OR "
        "(basis='full_text' AND document_id IS NOT NULL AND chunk_id IS NOT NULL "
        "AND page_number IS NOT NULL AND page_number>=1)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_evidence_basis_location"), "evidence", type_="check")
    op.create_check_constraint(
        "basis_location",
        "evidence",
        "(basis='abstract' AND source_id IS NOT NULL AND document_id IS NULL "
        "AND chunk_id IS NULL AND page_number IS NULL) OR "
        "(basis='full_text' AND document_id IS NOT NULL AND chunk_id IS NOT NULL "
        "AND page_number>=1)",
    )
