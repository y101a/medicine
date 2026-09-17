"""Persist encrypted retrieval citation snapshots on assistant messages.

Revision ID: 20260912_0010
Revises: 20260911_0009
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_0010"
down_revision = "20260911_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("citations_ciphertext", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "citations_ciphertext")
