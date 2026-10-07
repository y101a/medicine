"""N2 链路（适配器 + 抓取前校验 + 刷新运行）：**全部离线**，外网用假 fetcher 替代。"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.models import NewsItem, NewsRefreshRun, NewsSource
from app.news_cli import normalized_chinese_title
from app.services import news as news_service
from app.services.news.adapters import parse_for_source, parse_who_outbreak_news
from app.services.news.catalog import BLOCKED_SOURCES, CATALOG, PENDING_SOURCES
from app.services.news.feeds import FeedEntry, FeedParseError
from app.services.news.fetcher import FetchError, assert_public_endpoint, fetch_document
from app.services.news.refresh import refresh_sources

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _isolate_news_tables(profile_context):
    """同 `tests/test_news.py`：测试事务内先清空资讯三表，回滚后真实数据仍在。"""
    _client, db, _users = profile_context
    await db.execute(delete(NewsItem))
    await db.execute(delete(NewsSource))
    await db.execute(delete(NewsRefreshRun))
    await db.flush()
    yield

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
    assert "beijing_wjw_health" in CATALOG
    assert "who_zh_news" in CATALOG
    assert set(CATALOG) & set(BLOCKED_SOURCES) == set()
    assert "ecdc_news" in PENDING_SOURCES
    assert "ecdc_news" not in CATALOG  # 署名/许可标记未接线前不可通过 CLI 启用
    assert "nmpaic_news" in PENDING_SOURCES
    assert "nmpaic_news" not in CATALOG
    assert "chinanutri_health_education" in PENDING_SOURCES
    assert "chinanutri_health_education" not in CATALOG


def test_beijing_cards_use_full_chinese_title_display_date_and_relevance_filter():
    sample = '''<div class="weinei_left_con">
      <div class="weinei_left_con_line">
        <div class="weinei_left_con_line_text"><a
          href="./202609/t20260928_4883552.html"
          title="中秋国庆假期来啦~健康提示请您查收！">
          <span class="pc-hide">中秋国庆假期来啦~健康提示请您查收！</span>
          <span class="mobile-show">中秋国庆假期来啦~健康提示请...</span>
        </a></div><div class="weinei_left_con_line_date">2026-09-25</div>
      </div>
      <div class="weinei_left_con_line"><a href="./202609/t20260928_4883523.html"
        title="“飞行的硫酸”来了？紧急提醒"></a>
        <div class="weinei_left_con_line_date">2026-09-17</div></div>
      <div class="weinei_left_con_line"><a href="./202609/t20260911_4860170.html"
        title="2026年服贸会健康卫生服务专题创新成果发布活动在京举行"></a>
        <div class="weinei_left_con_line_date">2026-09-10</div></div>
      <div class="weinei_left_con_line"><a href="./202609/t20260911_4860165.html"
        title="2026服贸会健康卫生服务专题今日正式启幕"></a>
        <div class="weinei_left_con_line_date">2026-09-09</div></div>
      <div class="weinei_left_con_line"><a href="./202609/t20260902_4847952.html">
        <span class="pc-hide">北京初秋花粉高峰来了！过敏人群速看防护要点</span>
        <span class="mobile-show">北京初秋花粉高峰来了！过敏...</span></a>
        <div class="weinei_left_con_line_date">2026-09-02</div></div>
      <div class="weinei_left_con_line"><a href="./202608/t20260821_1234567.html"
        title="关于HPV免疫规划接种家长最关心的9个问题"></a>
        <div class="weinei_left_con_line_date">2026-08-21</div></div>
      <div class="weinei_left_con_line"><a href="./202608/t20260820_1234567.html"
        title="老年人合理用药指导项目公开遴选公告"></a>
        <div class="weinei_left_con_line_date">2026-08-20</div></div>
      <div class="weinei_left_con_line"><a href="https://evil.example/202608/t20260819_123.html"
        title="安全用药提示"></a>
        <div class="weinei_left_con_line_date">2026-08-19</div></div>
    </div>'''.encode()
    entries = parse_for_source("beijing_wjw_health", sample, fetch_mode="approved_page")
    assert [(entry.title, entry.category) for entry in entries] == [
        ("中秋国庆假期来啦~健康提示请您查收！", "wellness"),
        ("北京初秋花粉高峰来了！过敏人群速看防护要点", "disease"),
        ("关于HPV免疫规划接种家长最关心的9个问题", "disease"),
    ]
    assert entries[0].published_raw == "2026-09-25"  # 不从 URL 的 t20260928 猜日期。
    assert entries[0].url == (
        "https://wjw.beijing.gov.cn/xwzx_20031/xwfb/202609/t20260928_4883552.html"
    )
    assert all(entry.summary_raw is None for entry in entries)


@pytest.mark.parametrize("url", ["https://evil.example/a", "https://wjw.beijing.gov.cn.evil/a"])
async def test_beijing_direct_connection_rejects_other_hosts_without_network(url):
    with pytest.raises(FetchError) as error:
        await fetch_document(url, timeout_seconds=3, direct_beijing=True)
    assert error.value.code == "FETCH_DIRECT_NOT_ALLOWED"


def test_who_chinese_news_only_reads_disease_cards_and_same_site_links():
    sample = '''<html>
    <a href="/zh/news/item/25-09-2026-influenza-vaccine" class="link-container">
      <span class="timestamp">2026年9月25日</span>
      <p class="heading text-underline">世卫组织公布流感疫苗建议</p>
    </a>
    <a href="/zh/news/item/24-09-2026-meeting" class="link-container">
      <span class="timestamp">2026年9月24日</span><p class="heading">会议动态</p>
    </a>
    <a href="https://evil.example/zh/news/item/23-09-2026-virus" class="link-container">
      <span class="timestamp">2026年9月23日</span><p class="heading">病毒资讯</p>
    </a></html>'''.encode()
    entries = parse_for_source("who_zh_news", sample, fetch_mode="approved_page")
    assert len(entries) == 1
    assert entries[0].title == "世卫组织公布流感疫苗建议"
    assert entries[0].url == "https://www.who.int/zh/news/item/25-09-2026-influenza-vaccine"
    assert entries[0].published_raw == "2026-09-25"
    assert entries[0].summary_raw is None


def test_nmpaic_html_candidate_only_reads_same_site_article_metadata():
    sample = '''<html><ul class="glDivMain_boList">
    <li><a href="./202609/t20260929_431114.html">药品监管新消息</a>
    <span class="secBox1Right_bo_time">2026-09-25</span></li>
    <li><a href="https://evil.example/202609/t20260929_431114.html">外站消息</a>
    <span>2026-09-25</span></li>
    <li><a href="./202609/t20260928_431113.html">缺少日期</a></li>
    </ul></html>'''.encode()
    entries = parse_for_source("nmpaic_news", sample, fetch_mode="html_list")
    assert len(entries) == 1
    assert entries[0].title == "药品监管新消息"
    assert entries[0].url == "https://www.nmpaic.org.cn/yjzxyw/202609/t20260929_431114.html"
    assert entries[0].published_raw == "2026-09-25"
    assert entries[0].summary_raw is None


def test_chinanutri_candidate_splits_wellness_and_fitness_without_copying_text():
    sample = '''<html><div class="art_list">
    <a href="./202607/t20260710_1838065.html">
      <div class="fl">&gt; 认识肌少症筛查</div><div class="right">2026-07-10</div>
    </a>
    <a href="./202607/t20260710_1838062.html">
      <div class="fl">&gt; 小暑饮食攻略</div><div class="right">2026-07-10</div>
    </a>
    <a href="https://evil.example/a">
      <div class="fl">外站链接</div><div class="right">2026-07-10</div>
    </a>
    </div></html>'''.encode()
    entries = parse_for_source("chinanutri_health_education", sample, fetch_mode="html_list")
    assert [(entry.title, entry.category) for entry in entries] == [
        ("认识肌少症筛查", "fitness"),
        ("小暑饮食攻略", "wellness"),
    ]
    assert entries[0].url == (
        "https://www.chinanutri.cn/yyjkzxpt/yyjkkpzx/hdjl/202607/t20260710_1838065.html"
    )
    assert all(entry.summary_raw is None for entry in entries)


def test_manual_chinese_title_validation_is_bounded():
    assert normalized_chinese_title("  埃博拉病  暴发  ") == "埃博拉病 暴发"
    assert normalized_chinese_title("English only") is None
    assert normalized_chinese_title("<b>疫情</b>") is None
    assert normalized_chinese_title("中" * 301) is None


def test_ecdc_rss_candidate_parses_offline_without_copying_summary():
    sample = b'''<?xml version="1.0"?><rss><channel><item>
    <title>Ebola disease outbreak in the Democratic Republic of the Congo</title>
    <link>https://www.ecdc.europa.eu/en/news-events/ebola-update</link>
    <pubDate>Fri, 02 Oct 2026 17:36:21 +0200</pubDate>
    <description>Do not republish this summary</description>
    </item></channel></rss>'''
    entries = parse_for_source("ecdc_news", sample, fetch_mode="rss")
    assert len(entries) == 1
    assert entries[0].title.startswith("Ebola disease outbreak")
    assert entries[0].url == "https://www.ecdc.europa.eu/en/news-events/ebola-update"
    assert entries[0].published_raw is not None
    assert entries[0].summary_raw is None


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


def test_who_news_releases_adapter_uses_date_prefixed_slug():
    """新闻稿的真实地址带日期前缀（实测 200），必须用 ItemDefaultUrl 而不是 UrlName。"""
    payload = (
        b'{"value": ['
        b'{"Title": "WHO reports progress against tuberculosis",'
        b' "UrlName": "who-reports-progress-against-tuberculosis",'
        b' "ItemDefaultUrl": "/02-10-2026-who-reports-progress-against-tuberculosis",'
        b' "PublicationDateAndTime": "2026-10-02T08:09:03Z"},'
        b'{"Title": "", "UrlName": "empty-title"}]}'
    )

    entries = parse_for_source("who_news_releases", payload, fetch_mode="official_api")

    assert [entry.url for entry in entries] == [
        "https://www.who.int/news/item/02-10-2026-who-reports-progress-against-tuberculosis"
    ]
    assert entries[0].published_raw == "2026-10-02T08:09:03Z"
    assert entries[0].summary_raw is None


def test_who_general_news_releases_do_not_fill_disease_section():
    payload = (
        b'{"value": ['
        b'{"Title": "WHO appoints new regional director",'
        b' "ItemDefaultUrl": "/02-10-2026-new-regional-director"},'
        b'{"Title": "WHO launches cancer prevention initiative",'
        b' "ItemDefaultUrl": "/02-10-2026-cancer-prevention"}]}'
    )

    entries = parse_for_source("who_news_releases", payload, fetch_mode="official_api")

    assert [entry.title for entry in entries] == [
        "WHO launches cancer prevention initiative"
    ]


@pytest.mark.parametrize(
    ("source_id", "category", "payload"),
    [
        (
            "odphp_physical_activity",
            "fitness",
            b'<article><a class="c-teaser__link" href="/news/202610/physical-activity">'
            b'Physical Activity for Health</a><p class="node__submitted">'
            b'Posted on October 4, 2026 by ODPHP</p></article>',
        ),
        (
            "odphp_food_nutrition",
            "wellness",
            b'<article><a class="c-teaser__link" href="/news/202610/healthy-eating">'
            b'Healthy Eating Tips</a><p class="node__submitted">'
            b'Posted on October 4, 2026 by ODPHP</p></article>',
        ),
        (
            "fda_drug_updates",
            "medication",
            b'<rss><channel><item><title>FDA approves first drug for rare condition</title>'
            b'<link>http://www.fda.gov/drugs/resources-information-approved-drugs/approval</link>'
            b'<pubDate>Fri, 02 Oct 2026 15:31:02 EDT</pubDate></item></channel></rss>',
        ),
    ],
)
async def test_new_section_sources_refresh_into_correct_category(
    profile_context, source_id, category, payload
):
    _client, db, _users = profile_context
    spec = CATALOG[source_id]
    db.add(
        NewsSource(
            id=spec.id,
            name=spec.name,
            organization=spec.organization,
            homepage_url=spec.homepage_url,
            feed_url=spec.feed_url,
            fetch_mode=spec.fetch_mode,
            category_scope=list(spec.category_scope),
            license_note=spec.license_note,
            enabled=True,
        )
    )
    await db.flush()

    async def fetcher(_url: str, *, timeout_seconds: float):
        return "text/html" if spec.fetch_mode == "approved_page" else "application/rss+xml", payload

    summary = await refresh_sources(db, now=NOW, trigger="manual", fetcher=fetcher)
    page = await news_service.read_items(db, category=category, limit=20, offset=0, now=NOW)

    assert summary.status == "succeeded"
    assert summary.results[0].inserted == 1
    assert page.total == 1
    assert page.rows[0][0].category == category
    if source_id == "fda_drug_updates":
        assert page.rows[0][0].published_at == datetime(2026, 10, 2, 19, 31, 2, tzinfo=UTC)


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
