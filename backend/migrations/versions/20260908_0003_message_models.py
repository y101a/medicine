"""Store the model used for each assistant message."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0003"
down_revision = "20260906_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("messages", sa.Column("model_id", sa.String(128), nullable=True))
    op.add_column("messages", sa.Column("generation_status", sa.String(16), nullable=True))


def downgrade():
    op.drop_column("messages", "generation_status")
    op.drop_column("messages", "model_id")
    op.drop_column("messages", "provider")
