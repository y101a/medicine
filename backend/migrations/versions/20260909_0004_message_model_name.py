"""Store the model display name used for each assistant answer."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0004"
down_revision = "20260908_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("model_name", sa.String(128), nullable=True))


def downgrade():
    op.drop_column("messages", "model_name")
