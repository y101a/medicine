"""Add persistent AI educational document generation tasks.

Revision ID: 20260927_0024
Revises: 20260926_0023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260927_0024"
down_revision = "20260926_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consultation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_formats", postgresql.ARRAY(sa.String(length=8)), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("title_ciphertext", sa.Text(), nullable=True),
        sa.Column("content_plan_ciphertext", sa.Text(), nullable=True),
        sa.Column("source_snapshot_ciphertext", sa.Text(), nullable=True),
        sa.Column("source_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'generating', 'rendering', 'completed', 'failed', "
            "'cancelled', 'expired')",
            name=op.f("ck_generated_documents_status_supported"),
        ),
        sa.CheckConstraint(
            "cardinality(requested_formats) BETWEEN 1 AND 2 "
            "AND requested_formats <@ ARRAY['docx', 'pptx']::varchar[]",
            name=op.f("ck_generated_documents_formats_supported"),
        ),
        sa.CheckConstraint(
            "source_count >= 0",
            name=op.f("ck_generated_documents_source_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_generated_documents_attempt_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND title_ciphertext IS NOT NULL "
            "AND content_plan_ciphertext IS NOT NULL "
            "AND source_snapshot_ciphertext IS NOT NULL AND source_count > 0 "
            "AND expires_at IS NOT NULL AND completed_at IS NOT NULL) OR status <> 'completed'",
            name=op.f("ck_generated_documents_completed_state_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["consultation_id"],
            ["consultations.id"],
            name=op.f("fk_generated_documents_consultation_id_consultations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("fk_generated_documents_source_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_generated_documents_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_documents")),
    )
    op.create_index(
        "uq_generated_documents_user_client_request",
        "generated_documents",
        ["user_id", "client_request_id"],
        unique=True,
    )
    op.create_index(
        "uq_generated_documents_user_source_message",
        "generated_documents",
        ["user_id", "source_message_id"],
        unique=True,
    )
    op.create_index(
        "uq_generated_documents_user_active",
        "generated_documents",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'generating', 'rendering')"),
    )
    op.create_index(
        "ix_generated_documents_user_created",
        "generated_documents",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_generated_documents_status_lease",
        "generated_documents",
        ["status", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "ix_generated_documents_consultation_source_created",
        "generated_documents",
        ["consultation_id", "source_message_id", "created_at"],
    )
    op.create_index(
        "ix_generated_documents_expiry",
        "generated_documents",
        ["expires_at"],
        postgresql_where=sa.text("status = 'completed'"),
    )

    op.create_table(
        "generated_document_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("storage_key", sa.String(length=160), nullable=False),
        sa.Column("file_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "format IN ('docx', 'pptx')",
            name=op.f("ck_generated_document_files_format_supported"),
        ),
        sa.CheckConstraint(
            "byte_size > 0",
            name=op.f("ck_generated_document_files_byte_size_positive"),
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name=op.f("ck_generated_document_files_page_count_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["generated_documents.id"],
            name=op.f("fk_generated_document_files_generation_id_generated_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_document_files")),
    )
    op.create_index(
        "uq_generated_document_files_generation_format",
        "generated_document_files",
        ["generation_id", "format"],
        unique=True,
    )

    op.create_table(
        "generated_document_deletion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=160), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'retrying', 'completed', 'failed')",
            name=op.f("ck_generated_document_deletion_jobs_status_supported"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_generated_document_deletion_jobs_attempt_count_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_document_deletion_jobs")),
        sa.UniqueConstraint(
            "storage_key",
            name=op.f("uq_generated_document_deletion_jobs_storage_key"),
        ),
    )
    op.create_index(
        "ix_generated_document_deletion_due",
        "generated_document_deletion_jobs",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM generated_documents) + "
            "(SELECT count(*) FROM generated_document_deletion_jobs)"
        )
    )
    if count:
        raise RuntimeError("Cannot downgrade while generated document data exists")
    op.drop_index(
        "ix_generated_document_deletion_due",
        table_name="generated_document_deletion_jobs",
    )
    op.drop_table("generated_document_deletion_jobs")
    op.drop_index(
        "uq_generated_document_files_generation_format",
        table_name="generated_document_files",
    )
    op.drop_table("generated_document_files")
    op.drop_index("ix_generated_documents_expiry", table_name="generated_documents")
    op.drop_index(
        "ix_generated_documents_consultation_source_created",
        table_name="generated_documents",
    )
    op.drop_index("ix_generated_documents_status_lease", table_name="generated_documents")
    op.drop_index("ix_generated_documents_user_created", table_name="generated_documents")
    op.drop_index("uq_generated_documents_user_active", table_name="generated_documents")
    op.drop_index(
        "uq_generated_documents_user_source_message",
        table_name="generated_documents",
        if_exists=True,
    )
    op.drop_index(
        "uq_generated_documents_user_client_request",
        table_name="generated_documents",
    )
    op.drop_table("generated_documents")
