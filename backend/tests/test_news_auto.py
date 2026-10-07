"""N3：每日首次访问触发一轮有界自动刷新（不等待、不落自启动）。

用真实 HTTP 客户端打 `/api/v1/news`，但把后台任务的会话工厂换成**测试事务内的替身**
（`commit` 退化为 `flush`），所以刷新写入的数据随测试回滚，**不污染开发库**、也不会
把「今天已经自动跑过」的状态留给真实环境。
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import NewsItem, NewsRefreshRun, NewsSource
from app.services.auth import ACCESS_COOKIE
from app.services.news import auto as auto_module
from app.services.news import refresh as refresh_module
from app.services.news.fetcher import FetchError
from app.services.news.updates import update_day_for

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>测试源</title>
<item><title>测试条目一</title><link>https://example.org/news/one</link>
<pubDate>Sat, 03 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>
""".encode()


class _NoCommitSession:
    """后台任务的会话替身：`commit` 降级成 `flush`，写入留在测试事务里。"""

    def __init__(self, session) -> None:
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def commit(self) -> None:
        await self._session.flush()


def _source(*, enabled: bool = True) -> NewsSource:
    """非 WHO 的普通 RSS 来源：WHO 那个 id 有专用适配器，喂 RSS 会解析失败。"""
    return NewsSource(
        id="test_feed_source",
        name="测试 RSS 来源",
        organization="测试机构",
        homepage_url="https://example.org/news",
        feed_url="https://example.org/feed.xml",
        fetch_mode="rss",
        category_scope=["disease"],
        license_note="测试夹具：许可记录未写",
        enabled=enabled,
    )


@pytest.fixture(autouse=True)
async def _isolate_news_tables(profile_context):
    """同其他资讯测试：测试事务内先清空资讯三表，回滚后真实数据仍在。"""
    _client, db, _users = profile_context
    await db.execute(delete(NewsItem))
    await db.execute(delete(NewsSource))
    await db.execute(delete(NewsRefreshRun))
    await db.flush()
    yield


@pytest.fixture
def hooks(monkeypatch, profile_context):
    """换掉后台任务的会话与抓取函数，并打开 N3 开关；返回记录到的抓取 URL 列表。"""
    _client, db, _users = profile_context
    seen: list[str] = []

    async def _fake_fetcher(url: str, *, timeout_seconds: float):  # noqa: ARG001
        seen.append(url)
        return "application/rss+xml", RSS_SAMPLE

    monkeypatch.setattr(refresh_module, "fetch_document", _fake_fetcher)
    # 重试不要真的等 2 秒：这里只验证「重试了一次」。
    monkeypatch.setattr(refresh_module, "RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(
        auto_module, "SessionLocal", lambda: auto_module._SessionScope(_NoCommitSession(db))
    )
    monkeypatch.setattr(get_settings(), "news_portal_enabled", True)
    # conftest 默认关掉这条派发，这里显式打开以覆盖真实触发链路。
    monkeypatch.setattr(auto_module, "AUTO_REFRESH_ENABLED", True)
    return seen


def _auth(client, users) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(users[0].id))


async def _auto_runs(db) -> list[NewsRefreshRun]:
    result = await db.execute(
        select(NewsRefreshRun)
        .where(NewsRefreshRun.trigger == "auto")
        .order_by(NewsRefreshRun.started_at)
    )
    return list(result.scalars())


async def test_disabled_switch_never_fetches(profile_context, hooks, monkeypatch):
    """开关关着时：不出网、不留运行记录——这是默认状态。"""
    monkeypatch.setattr(get_settings(), "news_portal_enabled", False)
    client, db, users = profile_context
    db.add(_source())
    await db.flush()
    _auth(client, users)

    response = await client.get("/api/v1/news")

    assert response.status_code == 200
    assert hooks == []
    assert await _auto_runs(db) == []
    assert (await db.scalar(select(func.count()).select_from(NewsItem))) == 0


async def test_first_visit_runs_once_and_the_second_does_not(profile_context, hooks):
    client, db, users = profile_context
    db.add(_source())
    await db.flush()
    _auth(client, users)

    body = (await client.get("/api/v1/news")).json()

    assert body["refreshing"] is False
    assert hooks == ["https://example.org/feed.xml"]
    runs = await _auto_runs(db)
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert runs[0].source_ok_count == 1
    # 首次访问已经写入条目：下一次请求就能看到新内容。
    assert body["total"] == 0  # 这次响应拿到的仍是刷新前的快照
    second = (await client.get("/api/v1/news")).json()
    assert second["total"] == 1

    # 同一更新日再访问：不再抓第二次、也不再新增运行记录。
    assert hooks == ["https://example.org/feed.xml"]
    assert len(await _auto_runs(db)) == 1


async def test_transient_failure_is_retried_once_then_recorded(profile_context, hooks, monkeypatch):
    """瞬时错误重试一次；最终失败也只写受控错误码，响应照旧 200。"""
    calls: list[str] = []

    async def _always_timeout(url: str, *, timeout_seconds: float):  # noqa: ARG001
        calls.append(url)
        raise FetchError("FETCH_TIMEOUT")

    monkeypatch.setattr(refresh_module, "fetch_document", _always_timeout)
    client, db, users = profile_context
    source = _source()
    db.add(source)
    await db.flush()
    _auth(client, users)

    response = await client.get("/api/v1/news")

    assert response.status_code == 200
    assert len(calls) == 2  # 轮内重试了一次
    runs = await _auto_runs(db)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].source_failed_count == 1
    assert source.last_error_code == "FETCH_TIMEOUT"


async def test_refreshing_flag_is_reported_while_a_run_is_in_flight(profile_context, hooks):
    client, db, users = profile_context
    db.add(_source())
    now = datetime.now(UTC)
    db.add(
        NewsRefreshRun(
            update_day=update_day_for(now, hour=get_settings().news_update_hour),
            trigger="auto",
            status="running",
            started_at=now,
            lease_expires_at=now + timedelta(seconds=600),
        )
    )
    await db.flush()
    _auth(client, users)

    body = (await client.get("/api/v1/news")).json()

    assert body["refreshing"] is True
    # 当天已经有一轮在跑/跑过：不再抢第二次。
    assert hooks == []


async def test_no_sources_means_no_trigger(profile_context, hooks):
    client, _db, users = profile_context
    _auth(client, users)

    body = (await client.get("/api/v1/news")).json()

    assert body["status"] == "sources_not_connected"
    assert hooks == []


async def test_user_retry_once_after_failed_auto_run(profile_context, hooks, monkeypatch):
    client, db, users = profile_context
    db.add(_source())
    await db.flush()
    _auth(client, users)

    async def fail_fetch(_url: str, *, timeout_seconds: float):
        raise FetchError("FETCH_TIMEOUT")

    monkeypatch.setattr(refresh_module, "fetch_document", fail_fetch)
    assert (await client.get("/api/v1/news")).status_code == 200
    assert (await _auto_runs(db))[0].status == "failed"

    async def good_fetch(url: str, *, timeout_seconds: float):
        hooks.append(url)
        return "application/rss+xml", RSS_SAMPLE

    monkeypatch.setattr(refresh_module, "fetch_document", good_fetch)
    first = await client.post("/api/v1/news/refresh")
    assert first.status_code == 202
    assert first.json()["accepted"] is True
    assert first.json()["reason"] == "started"
    assert first.json()["nextRefreshAt"] is not None
    assert hooks == ["https://example.org/feed.xml"]
    assert (await client.get("/api/v1/news")).json()["total"] == 1

    second = await client.post("/api/v1/news/refresh")
    assert second.status_code == 202
    assert second.json()["accepted"] is False
    assert second.json()["reason"] == "already_ran_today"
    assert hooks == ["https://example.org/feed.xml"]
    manual_runs = await db.scalars(select(NewsRefreshRun).where(NewsRefreshRun.trigger == "manual"))
    assert len(list(manual_runs)) == 1


async def test_user_retry_is_denied_when_auto_succeeded(profile_context, hooks):
    client, db, users = profile_context
    db.add(_source())
    await db.flush()
    _auth(client, users)
    assert (await client.get("/api/v1/news")).status_code == 200

    response = await client.post("/api/v1/news/refresh")

    assert response.status_code == 202
    assert response.json()["accepted"] is False
    assert response.json()["reason"] == "already_ran_today"
    assert hooks == ["https://example.org/feed.xml"]


async def test_user_retry_respects_disabled_switch(profile_context, hooks, monkeypatch):
    client, db, users = profile_context
    db.add(_source())
    await db.flush()
    _auth(client, users)
    monkeypatch.setattr(get_settings(), "news_portal_enabled", False)

    response = await client.post("/api/v1/news/refresh")

    assert response.status_code == 202
    assert response.json()["accepted"] is False
    assert response.json()["reason"] == "disabled"
    assert hooks == []


async def test_user_retry_requires_login_and_waits_for_auto_failure(profile_context, hooks):
    client, db, users = profile_context
    db.add(_source())
    now = datetime.now(UTC)
    db.add(
        NewsRefreshRun(
            update_day=update_day_for(now, hour=get_settings().news_update_hour),
            trigger="auto",
            status="running",
            started_at=now,
            lease_expires_at=now + timedelta(seconds=600),
        )
    )
    await db.flush()

    assert (await client.post("/api/v1/news/refresh")).status_code == 401
    _auth(client, users)
    response = await client.post("/api/v1/news/refresh")

    assert response.status_code == 202
    assert response.json()["accepted"] is False
    assert response.json()["reason"] == "busy"
    assert hooks == []
