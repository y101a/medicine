"""Store encrypted deterministic triage results for user messages."""

import sqlalchemy as sa
from alembic import op

revision = "20260910_0005"
down_revision = "20260909_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("triage_ciphertext", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("messages", "triage_ciphertext")
