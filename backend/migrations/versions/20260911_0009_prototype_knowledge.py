"""Add isolated prototype knowledge statuses for local development."""

from alembic import op

revision = "20260911_0009"
down_revision = "20260911_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        op.f("ck_knowledge_sources_knowledge_source_ingestion_status"),
        "knowledge_sources",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_sources_knowledge_source_ingestion_status"),
        "knowledge_sources",
        "ingestion_status IN "
        "('candidate', 'prototype', 'approved', 'blocked', 'retired')",
    )
    op.drop_constraint(
        op.f("ck_knowledge_documents_knowledge_document_review_status"),
        "knowledge_documents",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_documents_knowledge_document_review_status"),
        "knowledge_documents",
        "review_status IN "
        "('pending', 'prototype', 'approved', 'rejected', 'superseded', 'expired')",
    )


def downgrade():
    op.execute(
        "UPDATE knowledge_documents SET review_status = 'rejected' "
        "WHERE review_status = 'prototype'"
    )
    op.execute(
        "UPDATE knowledge_sources SET ingestion_status = 'candidate' "
        "WHERE ingestion_status = 'prototype'"
    )
    op.drop_constraint(
        op.f("ck_knowledge_documents_knowledge_document_review_status"),
        "knowledge_documents",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_documents_knowledge_document_review_status"),
        "knowledge_documents",
        "review_status IN ('pending', 'approved', 'rejected', 'superseded', 'expired')",
    )
    op.drop_constraint(
        op.f("ck_knowledge_sources_knowledge_source_ingestion_status"),
        "knowledge_sources",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_sources_knowledge_source_ingestion_status"),
        "knowledge_sources",
        "ingestion_status IN ('candidate', 'approved', 'blocked', 'retired')",
    )
