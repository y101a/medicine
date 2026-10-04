"""来源适配器：把各来源的机器可读报文转成候选条目。

**只做结构化解析**：不写摘要（不转存来源摘要字段、不镜像正文），不翻译，不做医学加工。
"""

import json

from app.services.news.feeds import FeedEntry, FeedParseError, parse_feed

WHO_DON_ITEM_URL = "https://www.who.int/emergencies/disease-outbreak-news/item/{slug}"
WHO_NEWS_ITEM_URL = "https://www.who.int/news/item/{slug}"


def _parse_who_odata(payload: bytes, *, item_url: str) -> list[FeedEntry]:
    """WHO 官方 OData JSON 的通用解析。

    实测字段（2026-10-04）：`Title`、`ItemDefaultUrl`（真实路径末段，如 `/2026-DON618`、
    `/02-10-2026-...`）、`UrlName`（不带日期前缀的 slug）、`PublicationDateAndTime`（ISO Z）。
    **优先用 `ItemDefaultUrl`**：新闻稿的真实地址带日期前缀，用 `UrlName` 会 404。
    `summary_raw` 固定为 None：本产品不转存来源的摘要字段，只显示原题、来源与原文链接。
    """
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FeedParseError("MALFORMED_FEED") from error
    if not isinstance(document, dict):
        raise FeedParseError("MALFORMED_FEED")
    rows = document.get("value")
    if not isinstance(rows, list):
        raise FeedParseError("MALFORMED_FEED")

    entries: list[FeedEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("Title") or "").strip()
        slug = str(row.get("ItemDefaultUrl") or row.get("UrlName") or "").strip().lstrip("/")
        if not title or not slug or "/" in slug:
            continue
        published = row.get("PublicationDateAndTime") or row.get("PublicationDate")
        entries.append(
            FeedEntry(
                title=title,
                url=item_url.format(slug=slug),
                published_raw=str(published) if published else None,
                summary_raw=None,
            )
        )
    return entries


def parse_who_outbreak_news(payload: bytes) -> list[FeedEntry]:
    """WHO 疾病暴发新闻：条目地址为

    `https://www.who.int/emergencies/disease-outbreak-news/item/<DonId>`（实测 200）。
    """
    return _parse_who_odata(payload, item_url=WHO_DON_ITEM_URL)


def parse_who_news_releases(payload: bytes) -> list[FeedEntry]:
    """WHO 新闻稿：条目地址为 `https://www.who.int/news/item/<带日期前缀的 slug>`。

    2026-10-04 实测该地址 200；slug 必须取 `ItemDefaultUrl`，用 `UrlName` 会 404。
    """
    return _parse_who_odata(payload, item_url=WHO_NEWS_ITEM_URL)


#: 有专用适配器的来源；其余按 `fetch_mode` 走通用 RSS/Atom 解析。
_PARSERS = {
    "who_disease_outbreak_news": parse_who_outbreak_news,
    "who_news_releases": parse_who_news_releases,
}


def parse_for_source(source_id: str, payload: bytes, *, fetch_mode: str) -> list[FeedEntry]:
    parser = _PARSERS.get(source_id)
    if parser is not None:
        return parser(payload)
    if fetch_mode in ("rss", "atom"):
        return parse_feed(payload)
    raise FeedParseError("NO_ADAPTER")