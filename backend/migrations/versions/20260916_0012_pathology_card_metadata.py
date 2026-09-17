"""Track post-answer pathology cards and their source answers.

Revision ID: 20260916_0012
Revises: 20260914_0011
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0012"
down_revision = "20260914_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("answer_format", sa.String(length=16), server_default="plain", nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("is_medical_content", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_source_message_id",
        "messages",
        "messages",
        ["source_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_messages_source_card",
        "messages",
        ["source_message_id"],
        unique=True,
        postgresql_where=sa.text("source_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_messages_source_card", table_name="messages")
    op.drop_constraint("fk_messages_source_message_id", "messages", type_="foreignkey")
    op.drop_column("messages", "source_message_id")
    op.drop_column("messages", "is_medical_content")
    op.drop_column("messages", "answer_format")
