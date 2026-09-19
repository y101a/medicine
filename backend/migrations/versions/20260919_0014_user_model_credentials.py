"""Add encrypted per-user model provider credentials.

Revision ID: 20260919_0014
Revises: 20260916_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260919_0014"
down_revision: str | None = "20260916_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_model_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_model_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "provider IN ('deepseek', 'qwen', 'kimi', 'zhipuai')",
            name=op.f("ck_user_model_credentials_provider_supported"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_model_credentials")),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            name="uq_user_model_credentials_user_provider",
        ),
    )
    op.create_index(
        "ix_user_model_credentials_user_id",
        "user_model_credentials",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_model_credentials_user_id",
        table_name="user_model_credentials",
    )
    op.drop_table("user_model_credentials")
