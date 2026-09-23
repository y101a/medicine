"""Add durable medical image deletion jobs.

Revision ID: 20260923_0020
Revises: 20260922_0019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260923_0020"
down_revision = "20260922_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_deletion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "attempt_count >= 0",
            name=op.f("ck_image_deletion_jobs_attempt_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'retrying', 'completed', 'failed')",
            name=op.f("ck_image_deletion_jobs_status_supported"),
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL "
            "AND next_attempt_at IS NULL) OR "
            "(status = 'failed' AND completed_at IS NULL "
            "AND next_attempt_at IS NULL) OR "
            "(status IN ('pending', 'retrying') AND completed_at IS NULL "
            "AND next_attempt_at IS NOT NULL)",
            name=op.f("ck_image_deletion_jobs_state_supported"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_image_deletion_jobs")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_image_deletion_jobs_storage_key")),
    )
    op.create_index(
        "ix_image_deletion_jobs_due",
        "image_deletion_jobs",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    pending = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM image_deletion_jobs WHERE status IN ('pending', 'retrying')")
    )
    if pending:
        raise RuntimeError("Cannot downgrade while encrypted image deletion jobs are pending")
    op.drop_index("ix_image_deletion_jobs_due", table_name="image_deletion_jobs")
    op.drop_table("image_deletion_jobs")
