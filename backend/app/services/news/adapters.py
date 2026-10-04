"""来源适配器：把各来源的机器可读报文转成候选条目。

**只做结构化解析**：不写摘要（不转存来源摘要字段、不镜像正文），不翻译，不做医学加工。
"""

import json

from app.services.news.feeds import FeedEntry, FeedParseError, parse_feed

WHO_ITEM_URL = "https://www.who.int/emergencies/disease-outbreak-news/item/{slug}"


def parse_who_outbreak_news(payload: bytes) -> list[FeedEntry]:
    """WHO 疾病暴发新闻（OData JSON）。

    实测字段：`Title`、`UrlName`/`ItemDefaultUrl`（条目 slug）、`PublicationDateAndTime`（ISO Z）。
    条目地址形如 `https://www.who.int/emergencies/disease-outbreak-news/item/<slug>`（已实测 200）。
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
        slug = str(row.get("UrlName") or row.get("ItemDefaultUrl") or "").strip().lstrip("/")
        if not title or not slug or "/" in slug:
            continue
        published = row.get("PublicationDateAndTime") or row.get("PublicationDate")
        entries.append(
            FeedEntry(
                title=title,
                url=WHO_ITEM_URL.format(slug=slug),
                published_raw=str(published) if published else None,
                summary_raw=None,
            )
        )
    return entries


#: 有专用适配器的来源；其余按 `fetch_mode` 走通用 RSS/Atom 解析。
_PARSERS = {
    "who_disease_outbreak_news": parse_who_outbreak_news,
}


def parse_for_source(source_id: str, payload: bytes, *, fetch_mode: str) -> list[FeedEntry]:
    parser = _PARSERS.get(source_id)
    if parser is not None:
        return parser(payload)
    if fetch_mode in ("rss", "atom"):
        return parse_feed(payload)
    raise FeedParseError("NO_ADAPTER")