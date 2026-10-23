"""Persist document workflow checkpoint without storing user or model content.

Revision ID: 20261014_0032
Revises: 20261014_0031
"""

import sqlalchemy as sa
from alembic import op

revision = "20261014_0032"
down_revision = "20261014_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_documents",
        sa.Column("workflow_stage", sa.String(length=16), server_default="queued", nullable=False),
    )
    op.add_column(
        "generated_documents",
        sa.Column("multi_agent_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        "workflow_stage_supported",
        "generated_documents",
        "workflow_stage IN "
        "('queued', 'evidence', 'planner', 'writer', 'reviewer', 'layout', 'delivery')",
    )


def downgrade() -> None:
    op.drop_constraint("workflow_stage_supported", "generated_documents", type_="check")
    op.drop_column("generated_documents", "multi_agent_enabled")
    op.drop_column("generated_documents", "workflow_stage")
