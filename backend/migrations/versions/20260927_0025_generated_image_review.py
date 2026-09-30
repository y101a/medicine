"""Add Qwen generated-image visual review state and metadata.

Revision ID: 20260927_0025
Revises: 20260927_0024
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0025"
down_revision = "20260927_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generated_images", sa.Column("review_summary_ciphertext", sa.Text()))
    op.add_column("generated_images", sa.Column("review_model", sa.String(length=128)))
    op.add_column("generated_images", sa.Column("review_version", sa.String(length=64)))
    op.add_column(
        "generated_images",
        sa.Column("review_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "generated_images",
        sa.Column("regeneration_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_generated_images_review_attempt_count_nonnegative"),
        "generated_images",
        "review_attempt_count >= 0",
    )
    op.create_check_constraint(
        op.f("ck_generated_images_regeneration_count_supported"),
        "generated_images",
        "regeneration_count BETWEEN 0 AND 1",
    )
    op.drop_index("uq_generated_images_user_active", table_name="generated_images")
    op.drop_constraint(
        op.f("ck_generated_images_status_supported"), "generated_images", type_="check"
    )
    op.drop_constraint(
        op.f("ck_generated_images_storage_state_supported"),
        "generated_images",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_generated_images_status_supported"),
        "generated_images",
        "status IN ('submitted', 'running', 'reviewing', 'completed', 'failed', "
        "'cancelled', 'expired')",
    )
    op.create_check_constraint(
        op.f("ck_generated_images_storage_state_supported"),
        "generated_images",
        "(status = 'completed' AND storage_key IS NOT NULL "
        "AND image_key_ciphertext IS NOT NULL AND mime_type = 'image/webp' "
        "AND width IS NOT NULL AND height IS NOT NULL AND byte_size IS NOT NULL "
        "AND image_expires_at IS NOT NULL AND completed_at IS NOT NULL "
        "AND image_deleted_at IS NULL AND provider_task_id_ciphertext IS NULL) OR "
        "(status = 'reviewing' AND storage_key IS NOT NULL "
        "AND image_key_ciphertext IS NOT NULL AND mime_type = 'image/webp' "
        "AND width IS NOT NULL AND height IS NOT NULL AND byte_size IS NOT NULL "
        "AND image_expires_at IS NULL AND completed_at IS NULL "
        "AND image_deleted_at IS NULL AND provider_task_id_ciphertext IS NULL) OR "
        "(status NOT IN ('completed', 'reviewing') AND storage_key IS NULL "
        "AND image_key_ciphertext IS NULL AND mime_type IS NULL AND width IS NULL "
        "AND height IS NULL AND byte_size IS NULL)",
    )
    op.create_index(
        "uq_generated_images_user_active",
        "generated_images",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('submitted', 'running', 'reviewing')"),
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM generated_images WHERE status = 'reviewing' "
            "OR review_summary_ciphertext IS NOT NULL OR review_model IS NOT NULL "
            "OR review_version IS NOT NULL OR review_attempt_count <> 0 "
            "OR regeneration_count <> 0"
        )
    )
    if count:
        raise RuntimeError("Cannot downgrade while generated image review data exists")
    op.drop_index("uq_generated_images_user_active", table_name="generated_images")
    op.drop_constraint(
        op.f("ck_generated_images_storage_state_supported"),
        "generated_images",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_generated_images_status_supported"), "generated_images", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_generated_images_status_supported"),
        "generated_images",
        "status IN ('submitted', 'running', 'completed', 'failed', 'cancelled', 'expired')",
    )
    op.create_check_constraint(
        op.f("ck_generated_images_storage_state_supported"),
        "generated_images",
        "(status = 'completed' AND storage_key IS NOT NULL "
        "AND image_key_ciphertext IS NOT NULL AND mime_type = 'image/webp' "
        "AND width IS NOT NULL AND height IS NOT NULL AND byte_size IS NOT NULL "
        "AND image_expires_at IS NOT NULL AND completed_at IS NOT NULL "
        "AND image_deleted_at IS NULL AND provider_task_id_ciphertext IS NULL) OR "
        "(status <> 'completed' AND storage_key IS NULL AND image_key_ciphertext IS NULL "
        "AND mime_type IS NULL AND width IS NULL AND height IS NULL AND byte_size IS NULL)",
    )
    op.create_index(
        "uq_generated_images_user_active",
        "generated_images",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('submitted', 'running')"),
    )
    op.drop_constraint(
        op.f("ck_generated_images_regeneration_count_supported"),
        "generated_images",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_generated_images_review_attempt_count_nonnegative"),
        "generated_images",
        type_="check",
    )
    op.drop_column("generated_images", "regeneration_count")
    op.drop_column("generated_images", "review_attempt_count")
    op.drop_column("generated_images", "review_version")
    op.drop_column("generated_images", "review_model")
    op.drop_column("generated_images", "review_summary_ciphertext")
