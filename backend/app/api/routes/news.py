"""Authenticated news portal read API.

只读数据库里的最近成功快照，**不在请求里等待抓取**：当天首次访问时把「一轮有界刷新」挂到
后台任务（`app/services/news/auto.py`），请求立刻返回；抓取是否成功都不影响这次响应。
每日最多一轮由 `update_day` + 租约 + 唯一索引保证，服务停止就停止（无任何自启动）。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.dependencies import DbSession, get_current_user
from app.core.config import get_settings
from app.schemas.news import NewsCategory as CategoryParam
from app.schemas.news import NewsItemOut, NewsPageOut, NewsSourceStatusOut
from app.services import news as news_service
from app.services.news.auto import daily_auto_refresh

router = APIRouter(
    prefix="/news", tags=["健康资讯"], dependencies=[Depends(get_current_user)]
)


def _overall_status(
    *, total: int, has_success: bool, last_run_status: str | None, failed_sources: int
) -> str:
    """整体状态取受控码。来源失败不清空最近成功内容，但会显式标成 partial/stale。"""
    if total == 0:
        if last_run_status == "failed":
            return "failed"
        if has_success:
            return "stale"
        return "empty"
    if failed_sources or last_run_status in ("partial", "failed"):
        return "partial"
    return "ready"


@router.get("", response_model=NewsPageOut)
async def read_news(
    db: DbSession,
    background_tasks: BackgroundTasks,
    category: CategoryParam = "all",
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> NewsPageOut:
    settings = get_settings()
    now = datetime.now(UTC)

    sources = await news_service.enabled_sources(db)
    if not sources:
        # 尚未有任何经准入且启用的来源：明确说未接入，而不是给空列表充数。
        return NewsPageOut(category=category, status="sources_not_connected")

    page = await news_service.read_items(
        db, category=category, limit=limit, offset=offset, now=now
    )
    as_of = await news_service.latest_success_at(db)
    run = await news_service.latest_run(db)
    statuses = await news_service.source_statuses(db, now=now)
    failed_sources = sum(1 for item in statuses if item["status"] == "failed")
    refreshing = await news_service.running_auto_run(db, now=now) is not None

    if settings.news_portal_enabled:
        # 每日首次访问触发一轮有界刷新：**不等待**，失败也只写来源状态。
        background_tasks.add_task(daily_auto_refresh)

    return NewsPageOut(
        category=category,
        status=_overall_status(
            total=page.total,
            has_success=as_of is not None,
            last_run_status=run.status if run is not None else None,
            failed_sources=failed_sources,
        ),
        as_of=as_of,
        next_refresh_at=news_service.next_refresh_at(now, hour=settings.news_update_hour),
        items=[
            NewsItemOut(
                id=str(item.id),
                category=item.category,
                title=item.title,
                summary=item.summary,
                source_name=source.name,
                canonical_url=item.canonical_url,
                published_at=item.published_at,
                retrieved_at=item.last_seen_at,
                medical_reviewed=item.medical_reviewed,
            )
            for item, source in page.rows
        ],
        source_statuses=[
            NewsSourceStatusOut(
                id=str(entry["id"]),
                name=str(entry["name"]),
                status=entry["status"],
                last_success_at=entry["lastSuccessAt"],
                last_error_code=entry["lastErrorCode"],
            )
            for entry in statuses
        ],
        total=page.total,
        has_more=offset + len(page.rows) < page.total,
        refreshing=refreshing,
    )