"""Add optional Chinese news titles with explicit translation provenance.

Revision ID: 20261005_0030
Revises: 20261004_0029
"""

import sqlalchemy as sa
from alembic import op

revision = "20261005_0030"
down_revision = "20261004_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("news_items", sa.Column("title_zh", sa.String(length=300), nullable=True))
    op.add_column(
        "news_items", sa.Column("title_zh_source", sa.String(length=16), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_news_items_title_zh_provenance_valid"),
        "news_items",
        "(title_zh IS NULL AND title_zh_source IS NULL) OR "
        "(title_zh IS NOT NULL AND title_zh_source IN ('machine', 'manual'))",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_news_items_title_zh_provenance_valid"), "news_items", type_="check"
    )
    op.drop_column("news_items", "title_zh_source")
    op.drop_column("news_items", "title_zh")
