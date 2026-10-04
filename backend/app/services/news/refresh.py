"""一次刷新运行（N2）：显式触发、顺序抓取已启用来源、逐源记录受控状态。

**不注册任何自启动**：只有前台 CLI（以及以后 N3 的「每日首次访问触发」）会调用这里。
来源失败时保留最近成功快照并标 `partial`/`failed`，**不清空**已有条目。
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.news import NewsRefreshRun
from app.services.news import repository
from app.services.news.adapters import parse_for_source
from app.services.news.feeds import FeedParseError
from app.services.news.fetcher import FetchError, fetch_document
from app.services.news.updates import acquire_auto_run, finish_run, update_day_for

# 轮内重试（N3 的「超时/轮内重试」）：只对瞬时错误重试一次，避免把有限的一次运行耗在坏源上。
MAX_FETCH_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 2.0
TRANSIENT_FETCH_CODES = ("FETCH_TIMEOUT", "FETCH_FAILED")


def _is_transient(code: str) -> bool:
    """超时、连接失败与服务端 5xx 值得重试；4xx、类型不对、体积超限重试也没用。"""
    return code in TRANSIENT_FETCH_CODES or code.startswith("FETCH_HTTP_5")


@dataclass
class SourceResult:
    source_id: str
    status: str
    error_code: str | None = None
    fetched: int = 0
    inserted: int = 0
    refreshed: int = 0
    duplicate: int = 0
    rejected: int = 0


@dataclass
class RefreshSummary:
    update_day: date
    status: str
    run_id: int | None = None
    results: list[SourceResult] = field(default_factory=list)


async def refresh_sources(
    db: AsyncSession,
    *,
    now: datetime,
    trigger: str = "manual",
    source_ids: list[str] | None = None,
    limit: int | None = None,
    timeout_seconds: float | None = None,
    fetcher=None,
) -> RefreshSummary:
    """抓一轮。`fetcher=None` 时在**调用时**取默认抓取函数（便于测试注入替身）。

    `trigger="auto"` 需要 `news_portal_enabled` 打开，且同一更新日只跑一次；手动触发不受开关限制。
    """
    settings = get_settings()
    hour = settings.news_update_hour
    update_day = update_day_for(now, hour=hour)
    per_source = limit or settings.news_items_per_source
    timeout = timeout_seconds or settings.news_fetch_timeout_seconds

    if trigger == "auto" and not settings.news_portal_enabled:
        return RefreshSummary(update_day=update_day, status="skipped")

    sources = await repository.enabled_sources(db)
    if source_ids:
        wanted = set(source_ids)
        sources = [source for source in sources if source.id in wanted]
    if not sources:
        return RefreshSummary(update_day=update_day, status="skipped")

    if trigger == "auto":
        run = await acquire_auto_run(
            db,
            now=now,
            hour=hour,
            lease_seconds=settings.news_refresh_lease_seconds,
        )
        if run is None:
            # 当日自动运行已用过（或别的进程正在跑）：不重复、不补跑。
            return RefreshSummary(update_day=update_day, status="skipped")
    else:
        run = NewsRefreshRun(
            update_day=update_day,
            trigger="manual",
            status="running",
            started_at=now,
            lease_expires_at=now + timedelta(seconds=settings.news_refresh_lease_seconds),
        )
        db.add(run)
        await db.flush()

    results: list[SourceResult] = []
    fetch = fetcher or fetch_document
    for source in sources:
        source.last_attempt_at = now
        result = SourceResult(source_id=source.id, status="ok")
        endpoint = source.feed_url
        if not endpoint:
            result.status = "failed"
            result.error_code = "SOURCE_NO_ENDPOINT"
            source.last_error_code = result.error_code
            results.append(result)
            continue

        payload: bytes | None = None
        for attempt in range(MAX_FETCH_ATTEMPTS):
            try:
                _content_type, payload = await fetch(endpoint, timeout_seconds=timeout)
                break
            except FetchError as error:
                if attempt + 1 < MAX_FETCH_ATTEMPTS and _is_transient(error.code):
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue
                result.status = "failed"
                result.error_code = error.code
                source.last_error_code = error.code
                break
        if payload is None:
            results.append(result)
            continue

        try:
            entries = parse_for_source(
                source.id, payload, fetch_mode=source.fetch_mode
            )[:per_source]
            result.fetched = len(entries)
            outcome = await repository.upsert_entries(
                db,
                source=source,
                entries=entries,
                now=now,
                display_days=settings.news_display_days,
            )
            result.inserted = outcome.inserted
            result.refreshed = outcome.refreshed
            result.duplicate = outcome.duplicate
            result.rejected = len(outcome.rejected)
            source.last_success_at = now
            source.last_error_code = None
        except FeedParseError as error:
            result.status = "failed"
            result.error_code = str(error)[:32] or "PARSE_FAILED"
            source.last_error_code = result.error_code
        results.append(result)

    succeeded = sum(1 for item in results if item.status == "ok")
    failed = len(results) - succeeded
    if succeeded and not failed:
        status = "succeeded"
    elif succeeded:
        status = "partial"
    else:
        status = "failed"
    await finish_run(
        db,
        run=run,
        status=status,
        ok_count=succeeded,
        failed_count=failed,
        now=now,
        error_code=None,
    )
    return RefreshSummary(update_day=run.update_day, status=status, run_id=run.id, results=results)