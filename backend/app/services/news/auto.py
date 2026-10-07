"""N3 每日按需刷新：由 API 请求路径触发，但**不等待**、不落任何自启动。

`backend/docs/NEWS_UPDATE_PLAN.md` §2：当天首次访问且存在已准入来源时，服务端尝试触发
**同一应用生命周期内**的一轮有界刷新；持久化 `update_day` 与租约保证每日最多一轮自动刷新；
**接口不等待外网抓取完成，服务停止则刷新停止**。

因此这里只在后台任务里跑：请求已经返回，刷新跑完（或失败）都不影响用户看到的内容。
开关是 `news_portal_enabled`（默认 false）；关掉它，这条路径直接返回、一个字节都不出网。
"""

import logging
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.news.refresh import refresh_sources

logger = logging.getLogger(__name__)

#: 测试里由 `tests/conftest.py` 关闭：这条路径脱离请求事务、访问外网、写开发库，
#: 和健康记录抽取属于同一类派发（见 conftest 里 `_disable_news_auto_refresh`）。
#: 要覆盖真实触发链路的测试自行打开（`tests/test_news_auto.py`）。
AUTO_REFRESH_ENABLED = True


class _SessionScope:
    """`async with SessionLocal() as db` 的等价包装，便于测试注入自己的会话。"""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info) -> bool:
        return False


async def daily_auto_refresh(*, fetcher=None) -> None:
    """后台任务入口：抢到当日租约才抓取；异常一律吞掉记日志，不抛回请求。"""
    if not AUTO_REFRESH_ENABLED or not get_settings().news_portal_enabled:
        return

    try:
        async with SessionLocal() as db:
            summary = await refresh_sources(
                db, now=datetime.now(UTC), trigger="auto", fetcher=fetcher
            )
            await db.commit()
        logger.info("news auto refresh: %s (%s)", summary.status, summary.update_day)
    except Exception:  # noqa: BLE001 - 后台任务抛异常只会污染日志，救不回已返回的响应
        logger.exception("news auto refresh failed")


async def user_retry_refresh(run_id: int, *, fetcher=None) -> None:
    """已由 API 在数据库中预留的一次全站重试；后台不再创建第二条运行记录。"""
    if not AUTO_REFRESH_ENABLED or not get_settings().news_portal_enabled:
        return
    try:
        async with SessionLocal() as db:
            summary = await refresh_sources(
                db,
                now=datetime.now(UTC),
                trigger="manual",
                reserved_run_id=run_id,
                fetcher=fetcher,
            )
            await db.commit()
        logger.info("news user retry: %s (%s)", summary.status, summary.update_day)
    except Exception:  # noqa: BLE001 - 后台失败只记录日志，租约过期后按失败处理
        logger.exception("news user retry failed")
