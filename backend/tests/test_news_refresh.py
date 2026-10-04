"""N2 链路（适配器 + 抓取前校验 + 刷新运行）：**全部离线**，外网用假 fetcher 替代。"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.models import NewsSource
from app.services import news as news_service
from app.services.news.adapters import parse_for_source, parse_who_outbreak_news
from app.services.news.catalog import BLOCKED_SOURCES, CATALOG
from app.services.news.feeds import FeedEntry, FeedParseError
from app.services.news.fetcher import FetchError, assert_public_endpoint
from app.services.news.refresh import refresh_sources

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

WHO_SAMPLE = json.dumps(
    {
        "value": [
            {
                "Title": (
                    "Ebola disease caused by Bundibugyo virus - "
                    "Democratic Republic of the Congo"
                ),
                "UrlName": "2026-DON618",
                "ItemDefaultUrl": "/2026-DON618",
                "PublicationDateAndTime": "2026-09-25T15:16:26Z",
                "Summary": (
                    "Since the last Disease Outbreak News was published on 11 September 2026"
                ),
            },
            {"Title": "   ", "UrlName": "2026-DON619"},
            {"Title": "Cholera - Haiti", "UrlName": "nested/path"},
        ]
    }
).encode()


def _source(enabled: bool = True) -> NewsSource:
    spec = CATALOG["who_disease_outbreak_news"]
    return NewsSource(
        id=spec.id,
        name=spec.name,
        organization=spec.organization,
        homepage_url=spec.homepage_url,
        feed_url=spec.feed_url,
        fetch_mode=spec.fetch_mode,
        category_scope=list(spec.category_scope),
        license_note="测试夹具：许可记录未写",
        enabled=enabled,
    )


async def _attach_source(db, *, enabled: bool = True) -> NewsSource:
    """在测试事务里挂一个来源。

    先删掉库里可能已存在的同 id 行：真实试跑（N2）会在开发库留下提交过的来源行，
    测试再插同 id 会撞主键。删除发生在测试事务内，回滚后真实行仍在，不动环境数据。
    """
    spec = CATALOG["who_disease_outbreak_news"]
    await db.execute(delete(NewsSource).where(NewsSource.id == spec.id))
    await db.flush()
    source = _source(enabled=enabled)
    db.add(source)
    await db.flush()
    return source


async def _fake_fetcher(_url: str, *, timeout_seconds: float):  # noqa: ARG001
    return "application/json", WHO_SAMPLE


def test_who_adapter_keeps_original_title_and_link_only():
    entries = parse_who_outbreak_news(WHO_SAMPLE)
    assert len(entries) == 1
    assert entries[0].title.startswith("Ebola disease caused by Bundibugyo")
    assert entries[0].url == (
        "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON618"
    )
    assert entries[0].published_raw == "2026-09-25T15:16:26Z"
    # 不转存来源的摘要字段：本产品只显示原题、来源与原文链接。
    assert entries[0].summary_raw is None


def test_parse_for_source_rejects_unknown_adapter():
    with pytest.raises(FeedParseError) as error:
        parse_for_source("some_page_source", b"<html></html>", fetch_mode="approved_page")
    assert str(error.value) == "NO_ADAPTER"


@pytest.mark.parametrize(
    "url",
    ["https://127.0.0.1/x", "http://example.org/x", "https://10.1.2.3/x", "https://[::1]/x"],
)
async def test_assert_public_endpoint_rejects_before_any_network(url):
    with pytest.raises(FetchError) as error:
        await assert_public_endpoint(url)
    assert error.value.code == "FETCH_URL_REJECTED"


def test_catalog_and_blocked_sources_are_disjoint():
    assert "who_disease_outbreak_news" in CATALOG
    assert set(CATALOG) & set(BLOCKED_SOURCES) == set()


async def test_refresh_inserts_once_and_keeps_items_when_source_fails(profile_context):
    _client, db, _users = profile_context
    source = await _attach_source(db)

    summary = await refresh_sources(db, now=NOW, trigger="manual", fetcher=_fake_fetcher)
    assert summary.status == "succeeded"
    assert summary.results[0].source_id == source.id
    assert (summary.results[0].inserted, summary.results[0].fetched) == (1, 1)
    assert source.last_success_at is not None
    assert source.last_error_code is None

    page = await news_service.read_items(db, category="disease", limit=20, offset=0, now=NOW)
    assert page.total == 1
    item, joined = page.rows[0]
    assert joined.id == source.id
    assert item.medical_reviewed is False
    assert item.published_at == datetime(2026, 9, 25, 15, 16, 26, tzinfo=UTC)

    # 再跑一轮：同一条只刷新可见期，不重复入库。
    again = await refresh_sources(
        db, now=NOW + timedelta(hours=6), trigger="manual", fetcher=_fake_fetcher
    )
    assert (again.results[0].inserted, again.results[0].refreshed) == (0, 1)
    assert (
        await news_service.read_items(db, category="disease", limit=20, offset=0, now=NOW)
    ).total == 1

    # 来源失败：记录受控错误码，**保留**最近成功快照。
    async def _broken(_url: str, *, timeout_seconds: float):
        raise FetchError("FETCH_TIMEOUT")

    failed = await refresh_sources(
        db, now=NOW + timedelta(hours=12), trigger="manual", fetcher=_broken
    )
    assert failed.status == "failed"
    assert failed.results[0].error_code == "FETCH_TIMEOUT"
    assert source.last_error_code == "FETCH_TIMEOUT"
    assert (
        await news_service.read_items(db, category="disease", limit=20, offset=0, now=NOW)
    ).total == 1


async def test_auto_trigger_is_skipped_while_portal_disabled(profile_context):
    _client, db, _users = profile_context
    await _attach_source(db)

    summary = await refresh_sources(db, now=NOW, trigger="auto", fetcher=_fake_fetcher)
    # news_portal_enabled 默认 False：自动触发不抓外网。
    assert summary.status == "skipped"
    assert summary.run_id is None
    assert summary.results == []


async def test_refresh_without_enabled_sources_is_skipped(profile_context):
    _client, db, _users = profile_context
    await _attach_source(db, enabled=False)

    summary = await refresh_sources(db, now=NOW, trigger="manual", fetcher=_fake_fetcher)
    assert summary.status == "skipped"
    assert summary.results == []


async def test_same_title_updates_are_kept_when_published_times_differ(profile_context):
    """回归：WHO 同一疫情的多期更新共用标题，只有发布时间不同——不能压成一条。"""
    _client, db, _users = profile_context
    source = await _attach_source(db)

    def _entry(url: str, published: str | None) -> FeedEntry:
        return FeedEntry(
            title="Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo",
            url=url,
            published_raw=published,
            summary_raw=None,
        )

    outcome = await news_service.upsert_entries(
        db,
        source=source,
        entries=[
            _entry("https://example.org/don618", "2026-09-25T15:16:26Z"),
            _entry("https://example.org/don617", "2026-09-10T08:16:08Z"),
            # 同题 + 同发布时间 + 不同 URL：这才是同文多 URL，合并。
            _entry("https://example.org/don617-copy", "2026-09-10T08:16:08Z"),
        ],
        now=NOW,
        display_days=7,
    )
    assert (outcome.inserted, outcome.duplicate) == (2, 1)
    page = await news_service.read_items(db, category="disease", limit=20, offset=0, now=NOW)
    assert page.total == 2