"""健康资讯门户的独立数据层（`backend/docs/NEWS_UPDATE_PLAN.md` §3）。

刻意**不复用** `knowledge_*`：资讯不进入向量库、不进咨询检索，也不会自动升为正式医学知识。
来源准入是显式动作——只有 `enabled=True` 的来源才会被刷新器考虑，而写入 enabled 需要
逐站核对许可与 robots，属于 `medical_source_registry.json` 之外的**另一套**审核
（后者 `automated_collection_enabled=false` 是硬边界，不在本模块处理）。
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: 允许的分类。``all`` 只是查询聚合，不作为条目的分类落库。
NEWS_ITEM_CATEGORIES = ("wellness", "fitness", "disease", "medication")

NEWS_FETCH_MODES = ("rss", "atom", "official_api", "approved_page")
NEWS_RUN_STATUSES = ("running", "succeeded", "partial", "failed", "skipped")
NEWS_RUN_TRIGGERS = ("auto", "manual")


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organization: Mapped[str] = mapped_column(String(200), nullable=False)
    homepage_url: Mapped[str] = mapped_column(String(500), nullable=False)
    feed_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fetch_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="rss")
    #: 该来源允许发布的分类；未列出的分类即使条目自带也不收录。
    category_scope: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: 许可/robots 核对记录（谁、何时、结论）。空字符串表示尚未核对，来源不得启用。
    license_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "fetch_mode IN ('rss', 'atom', 'official_api', 'approved_page')",
            name="fetch_mode_supported",
        ),
        Index("ix_news_sources_enabled", "enabled", "id"),
    )


class NewsRefreshRun(Base):
    """一次刷新运行。自动运行按北京时间「更新日」唯一，用于保证每日最多一轮。"""

    __tablename__ = "news_refresh_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    update_day: Mapped[date] = mapped_column(Date, nullable=False)
    trigger: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ok_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        CheckConstraint("trigger IN ('auto', 'manual')", name="trigger_supported"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'skipped')",
            name="status_supported",
        ),
        CheckConstraint("source_ok_count >= 0", name="source_ok_count_non_negative"),
        CheckConstraint("source_failed_count >= 0", name="source_failed_count_non_negative"),
        # 自动运行：同一更新日只能有一条（手动运行不受限）。
        Index(
            "uq_news_refresh_runs_auto_day",
            "update_day",
            unique=True,
            postgresql_where=text("trigger = 'auto'"),
        ),
    )


class NewsItem(Base):
    """一条资讯。去重键是 `(source_id, canonical_url)`，并用标题指纹兜住同文多 URL。"""

    __tablename__ = "news_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    #: 可选的中文译题；原题始终保留在 title，翻译不会改去重指纹。
    title_zh: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: 译题来源。机器翻译必须明示，人工核对后才可标 manual。
    title_zh_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: 自编短摘要。无法可靠生成时为 NULL —— 只显示标题、来源与链接，不编造内容。
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    #: 原文发布时间；核实不到就是 NULL，**不允许**用抓取时间冒充。
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    medical_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source_id", "canonical_url", name="uq_news_items_source_url"),
        CheckConstraint(
            "category IN ('wellness', 'fitness', 'disease', 'medication')",
            name="category_supported",
        ),
        CheckConstraint(
            "(title_zh IS NULL AND title_zh_source IS NULL) OR "
            "(title_zh IS NOT NULL AND title_zh_source IN ('machine', 'manual'))",
            name="title_zh_provenance_valid",
        ),
        Index("ix_news_items_source_fingerprint", "source_id", "fingerprint"),
        Index("ix_news_items_category_last_seen", "category", "last_seen_at"),
    )
