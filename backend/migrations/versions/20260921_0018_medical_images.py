"""Add encrypted, expiring medical image attachments."""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0018"
down_revision = "20260921_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_attachments_kind_supported"), "attachments", type_="check")
    op.add_column("attachments", sa.Column("image_category", sa.String(32), nullable=True))
    op.add_column("attachments", sa.Column("mime_type", sa.String(64), nullable=True))
    op.add_column("attachments", sa.Column("image_width", sa.Integer(), nullable=True))
    op.add_column("attachments", sa.Column("image_height", sa.Integer(), nullable=True))
    op.add_column("attachments", sa.Column("image_storage_key", sa.String(128), nullable=True))
    op.add_column("attachments", sa.Column("image_key_ciphertext", sa.Text(), nullable=True))
    op.add_column(
        "attachments", sa.Column("image_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "attachments", sa.Column("image_deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("attachments", sa.Column("analysis_model", sa.String(64), nullable=True))
    op.add_column("attachments", sa.Column("analysis_version", sa.String(32), nullable=True))
    op.create_check_constraint(
        op.f("ck_attachments_kind_supported"),
        "attachments",
        "kind IN ('pdf', 'docx', 'pptx', 'txt', 'md', 'image')",
    )
    op.create_check_constraint(
        op.f("ck_attachments_image_category_supported"),
        "attachments",
        "image_category IS NULL OR image_category IN "
        "('report', 'medical_imaging', 'body_photo')",
    )
    op.create_check_constraint(
        op.f("ck_attachments_image_dimensions_supported"),
        "attachments",
        "(image_width IS NULL AND image_height IS NULL) OR "
        "(image_width BETWEEN 32 AND 2400 AND image_height BETWEEN 32 AND 2400)",
    )
    op.create_check_constraint(
        op.f("ck_attachments_image_metadata_required"),
        "attachments",
        "kind <> 'image' OR (image_category IS NOT NULL AND mime_type = 'image/webp' "
        "AND image_width IS NOT NULL AND image_height IS NOT NULL "
        "AND image_expires_at IS NOT NULL AND analysis_model IS NOT NULL "
        "AND analysis_version IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_attachments_image_storage_state_supported"),
        "attachments",
        "kind <> 'image' OR "
        "((image_storage_key IS NOT NULL AND image_key_ciphertext IS NOT NULL "
        "AND image_deleted_at IS NULL) OR "
        "(image_storage_key IS NULL AND image_key_ciphertext IS NULL "
        "AND image_deleted_at IS NOT NULL))",
    )
    op.create_index(
        "ix_attachments_image_expiry",
        "attachments",
        ["image_expires_at"],
        postgresql_where=sa.text("kind = 'image' AND image_deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_image_expiry", table_name="attachments")
    for name in (
        "image_storage_state_supported",
        "image_metadata_required",
        "image_dimensions_supported",
        "image_category_supported",
    ):
        op.drop_constraint(op.f(f"ck_attachments_{name}"), "attachments", type_="check")
    op.drop_constraint(op.f("ck_attachments_kind_supported"), "attachments", type_="check")
    for name in (
        "analysis_version",
        "analysis_model",
        "image_deleted_at",
        "image_expires_at",
        "image_key_ciphertext",
        "image_storage_key",
        "image_height",
        "image_width",
        "mime_type",
        "image_category",
    ):
        op.drop_column("attachments", name)
    op.create_check_constraint(
        op.f("ck_attachments_kind_supported"),
        "attachments",
        "kind IN ('pdf', 'docx', 'pptx', 'txt', 'md')",
    )
