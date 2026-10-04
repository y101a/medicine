"""健康资讯数据层（`backend/docs/NEWS_UPDATE_PLAN.md` N1）。

本包**不发起任何网络请求**：解析、校验、去重、过期与更新日计算全部离线，抓取字节由
以后接入的来源适配器提供（N2）。资讯与 `knowledge_*` 完全分开。
"""

from app.services.news.feeds import FeedEntry, parse_feed
from app.services.news.repository import (
    UpsertOutcome,
    enabled_sources,
    latest_success_at,
    read_items,
    source_statuses,
    upsert_entries,
    withdraw_source_items,
)
from app.services.news.updates import (
    acquire_auto_run,
    finish_run,
    latest_run,
    next_refresh_at,
    running_auto_run,
    update_day_for,
)
from app.services.news.validation import (
    Rejection,
    clean_summary,
    coerce_published_at,
    is_public_https_url,
    normalize_canonical_url,
    title_fingerprint,
    validate_entry,
)

__all__ = [
    "FeedEntry",
    "Rejection",
    "UpsertOutcome",
    "acquire_auto_run",
    "clean_summary",
    "coerce_published_at",
    "enabled_sources",
    "finish_run",
    "is_public_https_url",
    "latest_run",
    "latest_success_at",
    "next_refresh_at",
    "normalize_canonical_url",
    "parse_feed",
    "read_items",
    "running_auto_run",
    "source_statuses",
    "title_fingerprint",
    "update_day_for",
    "upsert_entries",
    "validate_entry",
    "withdraw_source_items",
]