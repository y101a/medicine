"""Add document reviewers and versioned URL snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20260911_0007"
down_revision = "20260911_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "knowledge_documents",
        sa.Column("legal_reviewed_by", sa.String(200), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("medical_reviewed_by", sa.String(200), nullable=True),
    )
    op.drop_constraint(
        op.f("uq_knowledge_documents_source_url"),
        "knowledge_documents",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_knowledge_documents_source_url_hash"),
        "knowledge_documents",
        ["source_id", "canonical_url", "content_hash"],
    )
    op.drop_constraint(
        op.f("ck_knowledge_documents_knowledge_document_approval_requirements"),
        "knowledge_documents",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_documents_knowledge_document_approval_requirements"),
        "knowledge_documents",
        "review_status <> 'approved' OR "
        "(legal_reviewed_at IS NOT NULL AND medical_reviewed_at IS NOT NULL "
        "AND legal_reviewed_by IS NOT NULL AND medical_reviewed_by IS NOT NULL "
        "AND license_type IS NOT NULL AND content_text IS NOT NULL)",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_knowledge_documents_knowledge_document_approval_requirements"),
        "knowledge_documents",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_documents_knowledge_document_approval_requirements"),
        "knowledge_documents",
        "review_status <> 'approved' OR "
        "(legal_reviewed_at IS NOT NULL AND medical_reviewed_at IS NOT NULL "
        "AND license_type IS NOT NULL AND content_text IS NOT NULL)",
    )
    op.drop_constraint(
        op.f("uq_knowledge_documents_source_url_hash"),
        "knowledge_documents",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_knowledge_documents_source_url"),
        "knowledge_documents",
        ["source_id", "canonical_url"],
    )
    op.drop_column("knowledge_documents", "medical_reviewed_by")
    op.drop_column("knowledge_documents", "legal_reviewed_by")
