"""一次刷新运行（N2）：显式触发、顺序抓取已启用来源、逐源记录受控状态。

**不注册任何自启动**：只有前台 CLI（以及以后 N3 的「每日首次访问触发」）会调用这里。
来源失败时保留最近成功快照并标 `partial`/`failed`，**不清空**已有条目。
"""

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
    fetcher=fetch_document,
) -> RefreshSummary:
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
        try:
            _content_type, payload = await fetcher(endpoint, timeout_seconds=timeout)
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
        except FetchError as error:
            result.status = "failed"
            result.error_code = error.code
            source.last_error_code = error.code
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