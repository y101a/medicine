"""Persist encrypted per-consultation rolling summaries.

Revision ID: 20261014_0031
Revises: 20261005_0030
"""

import sqlalchemy as sa
from alembic import op

revision = "20261014_0031"
down_revision = "20261005_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consultation_memories",
        sa.Column("consultation_id", sa.UUID(), nullable=False),
        sa.Column("covered_through_sequence", sa.Integer(), nullable=False),
        sa.Column("summary_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["consultation_id"], ["consultations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("consultation_id"),
        sa.CheckConstraint(
            "covered_through_sequence >= 1", name=op.f("ck_consultation_memories_sequence_positive")
        ),
    )


def downgrade() -> None:
    op.drop_table("consultation_memories")
