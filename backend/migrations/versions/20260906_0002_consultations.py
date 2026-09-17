"""Consultations and encrypted messages."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0002"
down_revision = "20260904_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "consultations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("client_request_id", sa.UUID(), nullable=False),
        sa.Column("title_ciphertext", sa.Text(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "client_request_id"),
    )
    op.create_index(
        "ix_consultations_user_updated", "consultations", ["user_id", "updated_at", "id"]
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "consultation_id",
            sa.UUID(),
            sa.ForeignKey("consultations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_request_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("consultation_id", "client_request_id", name="uq_messages_request"),
        sa.UniqueConstraint("consultation_id", "sequence", name="uq_messages_sequence"),
    )


def downgrade():
    op.drop_table("messages")
    op.drop_index("ix_consultations_user_updated", table_name="consultations")
    op.drop_table("consultations")
