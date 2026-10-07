"""更新日窗口与运行租约：保证「每日最多一轮自动刷新」，且不落任何持久化自启动。

更新日按 `Asia/Shanghai` 的 04:00 换日（`NEWS_UPDATE_PLAN.md` §2）：这是产品更新日，
不是「距离上次成功恰好 24 小时」。所有函数只写数据库，不发起网络请求。
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsRefreshRun

BEIJING = ZoneInfo("Asia/Shanghai")


def update_day_for(now: datetime, *, hour: int = 4) -> date:
    """北京时间 `hour` 点换日：凌晨 `hour` 点前仍算前一天。"""
    local = now.astimezone(BEIJING)
    if local.hour < hour:
        return local.date() - timedelta(days=1)
    return local.date()


def next_refresh_at(now: datetime, *, hour: int = 4) -> datetime:
    """下一个更新日切换时刻（UTC），给前端显示「下次更新」。"""
    local = now.astimezone(BEIJING)
    boundary = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if local >= boundary:
        boundary += timedelta(days=1)
    return boundary.astimezone(UTC)


async def running_auto_run(db: AsyncSession, *, now: datetime) -> NewsRefreshRun | None:
    """正在进行且租约未过期的自动或用户重试运行。"""
    result = await db.execute(
        select(NewsRefreshRun)
        .where(
            NewsRefreshRun.status == "running",
            NewsRefreshRun.lease_expires_at > now,
        )
        .order_by(NewsRefreshRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def acquire_user_retry_run(
    db: AsyncSession, *, now: datetime, hour: int = 4, lease_seconds: int = 900
) -> tuple[NewsRefreshRun | None, str]:
    """仅在当日自动运行失败/部分失败后，允许全站一次用户重试。

    锁住当天唯一的 auto 行，串行化多用户/多进程并发请求；CLI 的手动轮次也占用额度。
    调用方必须提交事务，再启动脱离请求事务的后台抓取。
    """
    day = update_day_for(now, hour=hour)
    auto_run = await db.scalar(
        select(NewsRefreshRun)
        .where(NewsRefreshRun.update_day == day, NewsRefreshRun.trigger == "auto")
        .with_for_update()
    )
    if auto_run is None:
        return None, "busy"
    if auto_run.status == "running":
        if auto_run.lease_expires_at > now:
            return None, "busy"
        auto_run.status = "failed"
        auto_run.error_code = "LEASE_EXPIRED"
        auto_run.finished_at = now
    if auto_run.status not in ("failed", "partial"):
        return None, "already_ran_today"
    manual_run = await db.scalar(
        select(NewsRefreshRun)
        .where(NewsRefreshRun.update_day == day, NewsRefreshRun.trigger == "manual")
        .order_by(NewsRefreshRun.started_at.desc())
        .limit(1)
    )
    if manual_run is not None:
        if manual_run.status == "running" and manual_run.lease_expires_at > now:
            return None, "busy"
        return None, "already_ran_today"
    run = NewsRefreshRun(
        update_day=day,
        trigger="manual",
        status="running",
        started_at=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
    )
    db.add(run)
    await db.flush()
    return run, "started"


async def latest_run(db: AsyncSession) -> NewsRefreshRun | None:
    result = await db.execute(
        select(NewsRefreshRun).order_by(NewsRefreshRun.started_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def acquire_auto_run(
    db: AsyncSession,
    *,
    now: datetime,
    hour: int = 4,
    lease_seconds: int = 900,
) -> NewsRefreshRun | None:
    """抢当天的自动运行权。同一更新日拿不到第二次——不自动无限重试。

    并发/多进程下靠 `uq_news_refresh_runs_auto_day` 唯一索引兜底：插入撞唯一约束就当
    别人已经抢到，返回 None（用 SAVEPOINT，不破坏调用方的事务）。
    """
    day = update_day_for(now, hour=hour)
    existing = await db.scalar(
        select(NewsRefreshRun).where(
            NewsRefreshRun.update_day == day, NewsRefreshRun.trigger == "auto"
        )
    )
    if existing is not None:
        if existing.status == "running" and existing.lease_expires_at <= now:
            # 上次跑到一半进程没了：标记失败，但今天不再自动补跑。
            existing.status = "failed"
            existing.error_code = "LEASE_EXPIRED"
            existing.finished_at = now
            await db.flush()
        return None

    run = NewsRefreshRun(
        update_day=day,
        trigger="auto",
        status="running",
        started_at=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
    )
    try:
        async with db.begin_nested():
            db.add(run)
    except IntegrityError:
        return None
    return run


async def finish_run(
    db: AsyncSession,
    *,
    run: NewsRefreshRun,
    status: str,
    ok_count: int,
    failed_count: int,
    now: datetime,
    error_code: str | None = None,
) -> None:
    """收尾一次运行，记录来源级成功/失败计数（受控状态码，不外泄异常原文）。"""
    run.status = status
    run.source_ok_count = ok_count
    run.source_failed_count = failed_count
    run.error_code = error_code
    run.finished_at = now
    await db.flush()
