"""Add encrypted consultation document attachments and reusable message links."""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0016"
down_revision = "20260920_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("consultation_id", sa.UUID(), nullable=False),
        sa.Column("display_name_ciphertext", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ready", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('pdf', 'docx', 'pptx', 'txt', 'md')",
            name="kind_supported",
        ),
        sa.CheckConstraint(
            "byte_size BETWEEN 1 AND 10485760",
            name="byte_size_supported",
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count BETWEEN 1 AND 30",
            name="page_count_supported",
        ),
        sa.CheckConstraint(
            "char_count BETWEEN 1 AND 500000",
            name="char_count_supported",
        ),
        sa.CheckConstraint("status = 'ready'", name="status_supported"),
        sa.ForeignKeyConstraint(
            ["consultation_id"],
            ["consultations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attachments_user_consultation_created",
        "attachments",
        ["user_id", "consultation_id", "created_at", "id"],
    )

    op.create_table(
        "attachment_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("attachment_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(length=64), nullable=False),
        sa.Column("content_ciphertext", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="position_nonnegative"),
        sa.CheckConstraint(
            "char_count BETWEEN 1 AND 4000",
            name="char_count_supported",
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["attachments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attachment_id",
            "position",
            name="uq_attachment_chunks_position",
        ),
    )
    op.create_index(
        "ix_attachment_chunks_attachment",
        "attachment_chunks",
        ["attachment_id", "position"],
    )

    op.create_table(
        "message_attachments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("attachment_id", sa.UUID(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 2", name="position_supported"),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["attachments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "attachment_id",
            name="uq_message_attachments_attachment",
        ),
        sa.UniqueConstraint(
            "message_id",
            "position",
            name="uq_message_attachments_position",
        ),
    )
    op.create_index(
        "ix_message_attachments_attachment",
        "message_attachments",
        ["attachment_id"],
    )
    op.create_index(
        "ix_message_attachments_message",
        "message_attachments",
        ["message_id", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_attachments_message", table_name="message_attachments")
    op.drop_index("ix_message_attachments_attachment", table_name="message_attachments")
    op.drop_table("message_attachments")
    op.drop_index("ix_attachment_chunks_attachment", table_name="attachment_chunks")
    op.drop_table("attachment_chunks")
    op.drop_index("ix_attachments_user_consultation_created", table_name="attachments")
    op.drop_table("attachments")
