"""Store encrypted PPT design templates per generated document.

Revision ID: 20260928_0026
Revises: 20260927_0025
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260928_0026"
down_revision = "20260927_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_documents",
        sa.Column("template_mode", sa.String(length=16), server_default="default", nullable=False),
    )
    op.create_check_constraint(
        "ck_generated_documents_template_mode_supported",
        "generated_documents",
        "template_mode IN ('default', 'builtin', 'uploaded')",
    )
    op.create_table(
        "generated_document_templates",
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=160), nullable=False),
        sa.Column("file_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "byte_size > 0", name=op.f("ck_generated_document_templates_byte_size_positive")
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["generated_documents.id"],
            name=op.f("fk_generated_document_templates_generation_id_generated_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("generation_id", name=op.f("pk_generated_document_templates")),
        sa.UniqueConstraint(
            "storage_key", name=op.f("uq_generated_document_templates_storage_key")
        ),
    )


def downgrade() -> None:
    op.drop_table("generated_document_templates")
    op.drop_constraint(
        "ck_generated_documents_template_mode_supported", "generated_documents", type_="check"
    )
    op.drop_column("generated_documents", "template_mode")
