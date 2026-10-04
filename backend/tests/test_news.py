"""资讯数据层（N1）：全部离线——不联网、不写任何真实来源。

覆盖 `backend/docs/NEWS_UPDATE_PLAN.md` §4 要求的禁 SSRF、重复、过期与撤回，以及
「每日最多一轮自动刷新」的更新日/租约逻辑。
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.security import create_access_token
from app.models import NewsItem, NewsRefreshRun, NewsSource
from app.services import news as news_service
from app.services.auth import ACCESS_COOKIE
from app.services.news.feeds import FeedEntry, FeedParseError, parse_feed
from app.services.news.validation import (
    coerce_published_at,
    is_public_https_url,
    normalize_canonical_url,
    title_fingerprint,
)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _isolate_news_tables(profile_context):
    """让资讯测试不受库里既有数据影响。

    后端测试与开发库共用同一个数据库，而这里的空态断例要求「没有启用来源」。开发库里可能有
    真实试跑留下的来源/条目/运行记录，所以先清空资讯三表。删除发生在测试事务内，
    回滚后真实数据仍在——不改测试环境以外的数据。
    """
    _client, db, _users = profile_context
    await db.execute(delete(NewsItem))
    await db.execute(delete(NewsSource))
    await db.execute(delete(NewsRefreshRun))
    await db.flush()
    yield

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>feed</title>
  <item>
    <title>  健康素养新提示 </title>
    <link>https://example.org/a</link>
    <pubDate>Sat, 03 Oct 2026 09:00:00 GMT</pubDate>
    <description>简短说明文字</description>
  </item>
</channel></rss>""".encode()

ATOM_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>运动安全须知</title>
    <link rel="alternate" href="https://example.org/b"/>
    <updated>2026-10-03T09:00:00Z</updated>
    <summary>说明文字</summary>
  </entry>
</feed>""".encode()


def _source(
    *,
    source_id: str = "news_test_source",
    enabled: bool = True,
    scope: tuple[str, ...] = ("wellness",),
) -> NewsSource:
    return NewsSource(
        id=source_id,
        name="测试来源",
        organization="测试机构",
        homepage_url="https://example.org",
        feed_url="https://example.org/feed.xml",
        fetch_mode="rss",
        category_scope=list(scope),
        license_note="测试夹具：未经来源准入，不得启用",
        enabled=enabled,
    )


def _entry(url: str, title: str, *, published: str | None = "2026-10-03T09:00:00Z") -> FeedEntry:
    return FeedEntry(title=title, url=url, published_raw=published, summary_raw="摘要文字")


async def test_news_shell_requires_login_and_never_invents_items(profile_context):
    client, _db, users = profile_context
    endpoint = "/api/v1/news"
    assert (await client.get(endpoint)).status_code == 401

    client.cookies.set(ACCESS_COOKIE, create_access_token(users[0].id))
    for category in ("all", "wellness", "fitness", "disease", "medication"):
        response = await client.get(endpoint, params={"category": category})
        assert response.status_code == 200
        body = response.json()
        assert body["category"] == category
        assert body["status"] == "sources_not_connected"
        assert body["asOf"] is None
        assert body["nextRefreshAt"] is None
        assert body["items"] == []
        assert body["tips"] == []
        assert body["sourceStatuses"] == []
        assert body["total"] == 0

    assert (await client.get(endpoint, params={"category": "invalid"})).status_code == 422


def test_parse_rss_and_atom_offline():
    rss = parse_feed(RSS_SAMPLE)
    assert len(rss) == 1
    assert rss[0].title.strip() == "健康素养新提示"
    assert rss[0].url == "https://example.org/a"
    assert rss[0].published_raw is not None

    atom = parse_feed(ATOM_SAMPLE)
    assert len(atom) == 1
    assert atom[0].url == "https://example.org/b"
    assert atom[0].summary_raw == "说明文字"

    with pytest.raises(FeedParseError) as malformed:
        parse_feed(b"<rss><channel><item>")
    assert str(malformed.value) == "MALFORMED_FEED"
    with pytest.raises(FeedParseError):
        parse_feed(b"")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/a",  # 只允许 HTTPS
        "https://127.0.0.1/a",
        "https://10.0.0.8/a",
        "https://192.168.1.10/a",
        "https://169.254.169.254/latest/meta-data",  # 云元数据地址
        "https://[::1]/a",
        "https://localhost/a",
        "https://printer.local/a",
        "https://example.org:8080/a",  # 非标准端口不作抓取目标
        "https://user:pass@example.org/a",
    ],
)
def test_url_validation_blocks_non_public_targets(url):
    assert is_public_https_url(url) is False
    assert is_public_https_url("https://www.example.org/news/a") is True


def test_canonical_url_drops_tracking_and_fragment():
    assert (
        normalize_canonical_url("HTTPS://Example.org/news/a/?utm_source=x&id=1#part")
        == "https://example.org/news/a?id=1"
    )
    assert normalize_canonical_url("not-a-url") is None


def test_title_fingerprint_is_stable_across_fullwidth_and_spacing():
    assert title_fingerprint("ＡＢＣ 新闻") == title_fingerprint("abc  新闻")


def test_published_at_is_never_fabricated():
    assert coerce_published_at("不是时间", now=NOW) is None
    assert coerce_published_at(None, now=NOW) is None
    # 明显来自未来（超过容忍期）的时间按「核实不到」处理。
    assert coerce_published_at("2027-01-01T00:00:00Z", now=NOW) is None
    parsed = coerce_published_at("2026-10-03T09:00:00Z", now=NOW)
    assert parsed == datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


def test_update_day_switches_at_beijing_0400():
    # 北京时间 03:59 仍算前一更新日；04:00 起算当天。
    assert news_service.update_day_for(datetime(2026, 10, 4, 19, 59, tzinfo=UTC)) == (
        datetime(2026, 10, 4).date()
    )
    assert news_service.update_day_for(datetime(2026, 10, 4, 20, 0, tzinfo=UTC)) == (
        datetime(2026, 10, 5).date()
    )
    assert news_service.next_refresh_at(datetime(2026, 10, 4, 12, 0, tzinfo=UTC)) == (
        datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
    )


async def test_auto_run_is_limited_to_one_per_update_day(profile_context):
    _client, db, _users = profile_context
    first = await news_service.acquire_auto_run(db, now=NOW, hour=4, lease_seconds=900)
    assert first is not None
    # 同一个更新日内再抢：拿不到（不自动无限重试）。
    assert await news_service.acquire_auto_run(db, now=NOW + timedelta(minutes=30), hour=4) is None
    # 下一个更新日可以再抢一轮。
    tomorrow = NOW + timedelta(days=1)
    assert await news_service.acquire_auto_run(db, now=tomorrow, hour=4) is not None


async def test_upsert_dedupes_expires_and_withdraws(profile_context):
    _client, db, _users = profile_context
    source = _source()
    db.add(source)
    await db.flush()

    outcome = await news_service.upsert_entries(
        db,
        source=source,
        entries=[
            _entry("https://example.org/a", "养生新知"),
            _entry("https://example.org/a?utm_source=share", "养生新知"),  # 同 URL 带追踪参数
            _entry("https://example.org/b", "养生新知"),  # 同文多 URL
            _entry("/relative/path", "没有域名的链接"),  # 不是完整网址
            _entry("http://example.org/c", "不安全的链接"),  # 非 HTTPS
            _entry("https://127.0.0.1/d", "内网地址"),  # SSRF
        ],
        now=NOW,
        display_days=7,
    )
    assert (outcome.inserted, outcome.refreshed, outcome.duplicate) == (1, 1, 1)
    assert [item.code for item in outcome.rejected] == [
        "INVALID_URL",
        "URL_NOT_PUBLIC_HTTPS",
        "URL_NOT_PUBLIC_HTTPS",
    ]

    page = await news_service.read_items(db, category="all", limit=20, offset=0, now=NOW)
    assert page.total == 1
    item, joined = page.rows[0]
    assert item.title == "养生新知"
    assert item.medical_reviewed is False
    assert item.published_at == datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    assert joined.id == source.id

    # 过展示期：不再出现在列表里，但行本身还在（便于追溯，不是删除）。
    item.expires_at = NOW - timedelta(minutes=1)
    await db.flush()
    expired = await news_service.read_items(db, category="all", limit=20, offset=0, now=NOW)
    assert expired.total == 0

    # 来源撤回：立即停止展示并可清空其条目。
    source.enabled = False
    await db.flush()
    hidden = await news_service.read_items(db, category="all", limit=20, offset=0, now=NOW)
    assert hidden.total == 0
    assert await news_service.withdraw_source_items(db, source_id=source.id) == 1


async def test_api_reports_ready_items_and_source_statuses(profile_context):
    client, db, users = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(users[0].id))

    ready = _source(source_id="news_ready_source")
    ready.last_success_at = NOW - timedelta(hours=3)
    broken = _source(source_id="news_broken_source")
    broken.last_error_code = "FETCH_TIMEOUT"
    db.add_all([ready, broken])
    await db.flush()
    await news_service.upsert_entries(
        db,
        source=ready,
        entries=[_entry("https://example.org/a", "养生新知")],
        now=NOW,
        display_days=7,
    )

    body = (await client.get("/api/v1/news")).json()
    # 有可用内容但有一个来源失败：整体标 partial，不谎称全部正常。
    assert body["status"] == "partial"
    assert body["total"] == 1
    assert body["hasMore"] is False
    assert body["asOf"] is not None
    assert body["nextRefreshAt"] is not None
    item = body["items"][0]
    assert item["sourceName"] == "测试来源"
    assert item["canonicalUrl"] == "https://example.org/a"
    assert item["medicalReviewed"] is False
    assert item["retrievedAt"] is not None
    statuses = {entry["id"]: entry["status"] for entry in body["sourceStatuses"]}
    assert statuses == {"news_ready_source": "ready", "news_broken_source": "failed"}

    # 分类过滤：条目不进别的分类。
    assert (await client.get("/api/v1/news", params={"category": "fitness"})).json()["total"] == 0


async def test_api_reports_failed_when_nothing_is_available(profile_context):
    client, db, users = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(users[0].id))

    source = _source(source_id="news_failed_source")
    source.last_error_code = "FETCH_TIMEOUT"
    db.add(source)
    await db.flush()
    run = await news_service.acquire_auto_run(db, now=NOW, hour=4)
    assert run is not None
    await news_service.finish_run(
        db, run=run, status="failed", ok_count=0, failed_count=1, now=NOW, error_code="FETCH_FAILED"
    )

    body = (await client.get("/api/v1/news")).json()
    assert body["status"] == "failed"
    assert body["items"] == []
    assert body["sourceStatuses"][0]["lastErrorCode"] == "FETCH_TIMEOUT"