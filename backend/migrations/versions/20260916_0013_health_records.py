"""Add encrypted per-user health records and collection settings.

Revision ID: 20260916_0013
Revises: 20260916_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260916_0013"
down_revision: str | None = "20260916_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

health_record_category_enum = sa.Enum(
    "general_status",
    "symptom",
    "condition",
    "medication",
    "allergy",
    "lifestyle",
    "measurement",
    "care_seeking",
    "other",
    name="health_record_category_enum",
)
health_record_source_enum = sa.Enum(
    "onboarding",
    "conversation",
    "user",
    name="health_record_source_enum",
)


def upgrade() -> None:
    op.create_table(
        "health_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", health_record_category_enum, nullable=False),
        sa.Column("content_ciphertext", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source", health_record_source_enum, nullable=False),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_health_records_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("fk_health_records_source_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_health_records")),
        sa.UniqueConstraint(
            "user_id",
            "category",
            "content_hash",
            name="uq_health_records_user_category_hash",
        ),
    )
    op.create_index(
        "ix_health_records_user_recorded",
        "health_records",
        ["user_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "health_record_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "collection_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("notice_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_extracted_message_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_health_record_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_health_record_settings")),
    )


def downgrade() -> None:
    op.drop_table("health_record_settings")
    op.drop_index("ix_health_records_user_recorded", table_name="health_records")
    op.drop_table("health_records")
    health_record_source_enum.drop(op.get_bind(), checkfirst=True)
    health_record_category_enum.drop(op.get_bind(), checkfirst=True)