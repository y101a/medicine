"""Add the health news portal data layer (sources, refresh runs, items).

Revision ID: 20261004_0029
Revises: 20261002_0028

只建资讯自己的三张表：资讯不进入 ``knowledge_*``、向量库或咨询检索
（``backend/docs/NEWS_UPDATE_PLAN.md`` §3）。约束按模型元数据逐字冻结，不在迁移里
import 应用代码——迁移是历史快照。

注意：本迁移**不写入任何来源**。来源准入是显式动作（N0/N2），未核准来源不得抓取，
`enabled` 默认 false。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261004_0029"
down_revision = "20261002_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_sources",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("organization", sa.String(length=200), nullable=False),
        sa.Column("homepage_url", sa.String(length=500), nullable=False),
        sa.Column("feed_url", sa.String(length=500), nullable=True),
        sa.Column("fetch_mode", sa.String(length=24), nullable=False),
        sa.Column("category_scope", sa.JSON(), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "fetch_mode IN ('rss', 'atom', 'official_api', 'approved_page')",
            name=op.f("ck_news_sources_fetch_mode_supported"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_news_sources_enabled", "news_sources", ["enabled", "id"], unique=False)

    op.create_table(
        "news_refresh_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("update_day", sa.Date(), nullable=False),
        sa.Column("trigger", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ok_count", sa.Integer(), nullable=False),
        sa.Column("source_failed_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "trigger IN ('auto', 'manual')", name=op.f("ck_news_refresh_runs_trigger_supported")
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'skipped')",
            name=op.f("ck_news_refresh_runs_status_supported"),
        ),
        sa.CheckConstraint(
            "source_ok_count >= 0", name=op.f("ck_news_refresh_runs_source_ok_count_non_negative")
        ),
        sa.CheckConstraint(
            "source_failed_count >= 0",
            name=op.f("ck_news_refresh_runs_source_failed_count_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 同一更新日的自动运行只允许一条；手动运行不受限。
    op.create_index(
        "uq_news_refresh_runs_auto_day",
        "news_refresh_runs",
        ["update_day"],
        unique=True,
        postgresql_where=sa.text("trigger = 'auto'"),
    )

    op.create_table(
        "news_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.String(length=1000), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("medical_reviewed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "category IN ('wellness', 'fitness', 'disease', 'medication')",
            name=op.f("ck_news_items_category_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["news_sources.id"], name=op.f("fk_news_items_source_id_news_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "canonical_url", name="uq_news_items_source_url"),
    )
    op.create_index(
        "ix_news_items_source_fingerprint", "news_items", ["source_id", "fingerprint"], unique=False
    )
    op.create_index(
        "ix_news_items_category_last_seen", "news_items", ["category", "last_seen_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_news_items_category_last_seen", table_name="news_items")
    op.drop_index("ix_news_items_source_fingerprint", table_name="news_items")
    op.drop_table("news_items")
    op.drop_index("uq_news_refresh_runs_auto_day", table_name="news_refresh_runs")
    op.drop_table("news_refresh_runs")
    op.drop_index("ix_news_sources_enabled", table_name="news_sources")
    op.drop_table("news_sources")