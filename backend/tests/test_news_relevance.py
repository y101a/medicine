"""专区相关性的纯解析回归；不依赖新闻表或 PostgreSQL。"""

import json

from app.services.news.adapters import parse_for_source
from app.services.news.catalog import CATALOG


def test_general_who_releases_exclude_unrelated_organization_news():
    payload = json.dumps(
        {
            "value": [
                {
                    "Title": "WHO appoints new regional director",
                    "ItemDefaultUrl": "/02-10-2026-new-regional-director",
                },
                {
                    "Title": "WHO launches cancer prevention initiative",
                    "ItemDefaultUrl": "/02-10-2026-cancer-prevention",
                },
            ]
        }
    ).encode()

    entries = parse_for_source("who_news_releases", payload, fetch_mode="official_api")

    assert [entry.title for entry in entries] == [
        "WHO launches cancer prevention initiative"
    ]


def test_outbreak_source_keeps_disease_updates_without_title_keyword_filter():
    payload = json.dumps(
        {
            "value": [
                {
                    "Title": "Cholera - Haiti",
                    "ItemDefaultUrl": "/2026-DON618",
                }
            ]
        }
    ).encode()

    entries = parse_for_source("who_disease_outbreak_news", payload, fetch_mode="official_api")

    assert [entry.title for entry in entries] == ["Cholera - Haiti"]


def test_odphp_topic_pages_keep_only_relevant_same_site_articles():
    page = b'''<article class="node node--type-blog-post">
      <a class="c-teaser__link" href="/news/202607/get-moving">Get Moving Safely</a>
      <p class="node__submitted">Posted on July 16, 2026 by ODPHP</p>
    </article>
    <article><a class="c-teaser__link" href="/news/202607/meeting">New meeting announced</a>
      <p class="node__submitted">Posted on July 15, 2026 by ODPHP</p></article>
    <article><a class="c-teaser__link" href="https://evil.example/news/202607/exercise">
      Exercise from another site</a>
      <p class="node__submitted">Posted on July 14, 2026 by ODPHP</p></article>'''

    entries = parse_for_source("odphp_physical_activity", page, fetch_mode="approved_page")

    assert [(entry.title, entry.category, entry.published_raw) for entry in entries] == [
        ("Get Moving Safely", "fitness", "2026-07-16")
    ]
    assert entries[0].url == "https://odphp.health.gov/news/202607/get-moving"
    assert entries[0].summary_raw is None


def test_odphp_nutrition_page_keeps_food_topic_only():
    page = b'''<article><a class="c-teaser__link" href="/news/202609/nutrition">
      Healthy Eating and Nutrition</a>
      <p class="node__submitted">Posted on September 3, 2026 by ODPHP</p></article>
    <article><a class="c-teaser__link" href="/news/202609/policy">
      New public comment period</a>
      <p class="node__submitted">Posted on September 2, 2026 by ODPHP</p></article>'''

    entries = parse_for_source("odphp_food_nutrition", page, fetch_mode="approved_page")

    assert [entry.title for entry in entries] == ["Healthy Eating and Nutrition"]
    assert entries[0].category == "wellness"


def test_fda_drug_feed_rejects_admin_items_and_external_links():
    feed = b'''<rss><channel>
      <item><title>FDA approves first drug for rare condition</title>
        <link>http://www.fda.gov/drugs/resources-information-approved-drugs/approval</link>
        <pubDate>Fri, 02 Oct 2026 15:31:02 EDT</pubDate><description>Do not copy</description>
      </item>
      <item><title>FDA appoints new director</title>
        <link>https://www.fda.gov/drugs/news-events/director</link></item>
      <item><title>FDA approves a drug</title>
        <link>https://evil.example/drugs/approval</link></item>
    </channel></rss>'''

    entries = parse_for_source("fda_drug_updates", feed, fetch_mode="rss")

    assert len(entries) == 1
    assert entries[0].url == (
        "https://www.fda.gov/drugs/resources-information-approved-drugs/approval"
    )
    assert entries[0].published_raw == "Fri, 02 Oct 2026 15:31:02 -0400"
    assert entries[0].summary_raw is None


def test_three_new_sources_are_separate_approved_sections():
    assert CATALOG["odphp_physical_activity"].category_scope == ("fitness",)
    assert CATALOG["odphp_food_nutrition"].category_scope == ("wellness",)
    assert CATALOG["fda_drug_updates"].category_scope == ("medication",)
