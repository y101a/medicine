"""Add persistent AI educational illustration tasks.

Revision ID: 20260924_0022
Revises: 20260923_0021
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_0022"
down_revision = "20260923_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consultation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_ciphertext", sa.Text(), nullable=False),
        sa.Column("style", sa.String(length=32), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("provider_task_id_ciphertext", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(length=128), nullable=True),
        sa.Column("image_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("image_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("poll_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "style IN ('medical_illustration', 'flat_illustration', 'friendly_cartoon')",
            name=op.f("ck_generated_images_style_supported"),
        ),
        sa.CheckConstraint(
            "aspect_ratio IN ('1:1', '4:3', '3:4', '16:9')",
            name=op.f("ck_generated_images_aspect_ratio_supported"),
        ),
        sa.CheckConstraint(
            "status IN ('submitted', 'running', 'completed', 'failed', 'cancelled', 'expired')",
            name=op.f("ck_generated_images_status_supported"),
        ),
        sa.CheckConstraint(
            "poll_count >= 0",
            name=op.f("ck_generated_images_poll_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND storage_key IS NOT NULL "
            "AND image_key_ciphertext IS NOT NULL AND mime_type = 'image/webp' "
            "AND width IS NOT NULL AND height IS NOT NULL AND byte_size IS NOT NULL "
            "AND image_expires_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND image_deleted_at IS NULL AND provider_task_id_ciphertext IS NULL) OR "
            "(status <> 'completed' AND storage_key IS NULL AND image_key_ciphertext IS NULL "
            "AND mime_type IS NULL AND width IS NULL AND height IS NULL AND byte_size IS NULL)",
            name=op.f("ck_generated_images_storage_state_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["consultation_id"],
            ["consultations.id"],
            name=op.f("fk_generated_images_consultation_id_consultations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("fk_generated_images_source_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_generated_images_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_images")),
    )
    op.create_index(
        "uq_generated_images_user_client_request",
        "generated_images",
        ["user_id", "client_request_id"],
        unique=True,
    )
    op.create_index(
        "uq_generated_images_user_active",
        "generated_images",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('submitted', 'running')"),
    )
    op.create_index(
        "ix_generated_images_user_created",
        "generated_images",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_generated_images_status_poll",
        "generated_images",
        ["status", "next_poll_at"],
    )
    op.create_index(
        "ix_generated_images_consultation_source_created",
        "generated_images",
        ["consultation_id", "source_message_id", "created_at"],
    )
    op.create_index(
        "ix_generated_images_expiry",
        "generated_images",
        ["image_expires_at"],
        postgresql_where=sa.text("status = 'completed'"),
    )
    op.create_table(
        "generated_image_delivery_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_consultation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_generated_image_delivery_logs"),
        ),
    )
    op.create_index(
        "uq_generated_image_delivery_content_recipient",
        "generated_image_delivery_logs",
        ["content_id", "recipient_fingerprint"],
        unique=True,
    )
    op.create_index(
        "ix_generated_image_delivery_retain_until",
        "generated_image_delivery_logs",
        ["retain_until"],
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM generated_images) + "
            "(SELECT count(*) FROM generated_image_delivery_logs)"
        )
    )
    if count:
        raise RuntimeError("Cannot downgrade while generated image tasks or delivery logs exist")
    op.drop_index(
        "ix_generated_image_delivery_retain_until",
        table_name="generated_image_delivery_logs",
    )
    op.drop_index(
        "uq_generated_image_delivery_content_recipient",
        table_name="generated_image_delivery_logs",
    )
    op.drop_table("generated_image_delivery_logs")
    op.drop_index("ix_generated_images_expiry", table_name="generated_images")
    op.drop_index("ix_generated_images_consultation_source_created", table_name="generated_images")
    op.drop_index("ix_generated_images_status_poll", table_name="generated_images")
    op.drop_index("ix_generated_images_user_created", table_name="generated_images")
    op.drop_index("uq_generated_images_user_active", table_name="generated_images")
    op.drop_index("uq_generated_images_user_client_request", table_name="generated_images")
    op.drop_table("generated_images")
