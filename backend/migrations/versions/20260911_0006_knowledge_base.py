"""Create curated medical knowledge base tables."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision = "20260911_0006"
down_revision = "20260910_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("organization", sa.String(200), nullable=False),
        sa.Column("channel_name", sa.String(300), nullable=False),
        sa.Column("authority_level", sa.String(64), nullable=False),
        sa.Column("jurisdiction", sa.String(16), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("entry_url", sa.Text(), nullable=False),
        sa.Column("legal_notice_url", sa.Text(), nullable=True),
        sa.Column("ingestion_status", sa.String(32), nullable=False),
        sa.Column(
            "automated_collection",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority BETWEEN 1 AND 9",
            name=op.f("ck_knowledge_sources_knowledge_source_priority"),
        ),
        sa.CheckConstraint(
            "ingestion_status IN ('candidate', 'approved', 'blocked', 'retired')",
            name=op.f("ck_knowledge_sources_knowledge_source_ingestion_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_sources")),
        sa.UniqueConstraint("source_key", name=op.f("uq_knowledge_sources_source_key")),
    )
    op.create_index(
        "ix_knowledge_sources_status_priority",
        "knowledge_sources",
        ["ingestion_status", "priority"],
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("responsible_department", sa.String(200), nullable=True),
        sa.Column(
            "authors",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("jurisdiction", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version_label", sa.String(100), nullable=True),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("license_type", sa.String(64), nullable=True),
        sa.Column("license_notes", sa.Text(), nullable=True),
        sa.Column("legal_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("medical_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("supersedes_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'superseded', 'expired')",
            name=op.f("ck_knowledge_documents_knowledge_document_review_status"),
        ),
        sa.CheckConstraint(
            "review_status <> 'approved' OR "
            "(legal_reviewed_at IS NOT NULL AND medical_reviewed_at IS NOT NULL "
            "AND license_type IS NOT NULL AND content_text IS NOT NULL)",
            name=op.f(
                "ck_knowledge_documents_knowledge_document_approval_requirements"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["knowledge_sources.id"],
            name=op.f("fk_knowledge_documents_source_id_knowledge_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_document_id"],
            ["knowledge_documents.id"],
            name=op.f(
                "fk_knowledge_documents_supersedes_document_id_knowledge_documents"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
        sa.UniqueConstraint(
            "source_id",
            "canonical_url",
            name="uq_knowledge_documents_source_url",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_source_review",
        "knowledge_documents",
        ["source_id", "review_status", "published_at"],
    )
    op.create_index(
        "ix_knowledge_documents_content_hash",
        "knowledge_documents",
        ["content_hash"],
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(500), nullable=True),
        sa.Column(
            "section_path",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", VECTOR(), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("embedding_version", sa.String(64), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name=op.f("ck_knowledge_chunks_knowledge_chunk_index_nonnegative"),
        ),
        sa.CheckConstraint(
            "token_count IS NULL OR token_count >= 0",
            name=op.f("ck_knowledge_chunks_knowledge_chunk_token_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL "
            "AND embedding_version IS NULL AND embedding_dimensions IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL "
            "AND embedding_version IS NOT NULL AND embedding_dimensions > 0)",
            name=op.f("ck_knowledge_chunks_knowledge_chunk_embedding_metadata"),
        ),
        sa.CheckConstraint(
            "embedding IS NULL OR vector_dims(embedding) = embedding_dimensions",
            name=op.f("ck_knowledge_chunks_knowledge_chunk_embedding_dimensions"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_chunks_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_index",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_document",
        "knowledge_chunks",
        ["document_id", "chunk_index"],
    )
    op.create_index(
        "ix_knowledge_chunks_content_hash",
        "knowledge_chunks",
        ["content_hash"],
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_model",
        "knowledge_chunks",
        ["embedding_model", "embedding_version"],
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_uri", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_ingestion_jobs_ingestion_job_status"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_ingestion_jobs_ingestion_job_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_ingestion_jobs_document_id_knowledge_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["knowledge_sources.id"],
            name=op.f("fk_ingestion_jobs_source_id_knowledge_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_ingestion_jobs_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_ingestion_jobs_status_created",
        "ingestion_jobs",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_index("ix_ingestion_jobs_status_created", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_knowledge_chunks_embedding_model", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_content_hash", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(
        "ix_knowledge_documents_content_hash", table_name="knowledge_documents"
    )
    op.drop_index(
        "ix_knowledge_documents_source_review", table_name="knowledge_documents"
    )
    op.drop_table("knowledge_documents")
    op.drop_index(
        "ix_knowledge_sources_status_priority", table_name="knowledge_sources"
    )
    op.drop_table("knowledge_sources")
    # The vector extension may be shared by other tables and is intentionally retained.
