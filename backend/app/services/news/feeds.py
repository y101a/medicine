"""把 RSS/Atom 字节解析成候选条目。**纯离线**：调用方负责取字节（N2 才接网络）。

用标准库 `xml.etree.ElementTree`：它默认不解析外部实体，也不会自己发请求（无 XXE 外联）。
命名空间一律按 local name 处理，避免各家 feed 的 ns 前缀差异。
"""

from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

MAX_ENTRIES_PER_FEED = 200


class FeedParseError(ValueError):
    """受控解析失败：只带短原因，不透传原始报文。"""


class FeedEntry:
    __slots__ = ("category", "published_raw", "summary_raw", "title", "url")

    def __init__(
        self,
        *,
        title: str,
        url: str,
        published_raw: str | None,
        summary_raw: str | None,
        category: str | None = None,
    ) -> None:
        self.title = title
        self.url = url
        self.published_raw = published_raw
        self.summary_raw = summary_raw
        #: 适配器可以按栏目给出分类；来源只声明一个分类时留空即可。
        self.category = category

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"FeedEntry(title={self.title!r}, url={self.url!r})"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first_text(node: ElementTree.Element, names: tuple[str, ...]) -> str | None:
    for child in node:
        if _local(child.tag) in names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return None


def _link(node: ElementTree.Element) -> str | None:
    """RSS 用 `<link>text</link>`；Atom 用 `<link href=... rel="alternate">`。"""
    fallback: str | None = None
    for child in node:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if href:
            rel = (child.get("rel") or "alternate").lower()
            if rel == "alternate":
                return href.strip()
            fallback = fallback or href.strip()
            continue
        text = (child.text or "").strip()
        if text:
            return text
        if child.get("href"):
            fallback = fallback or child.get("href", "").strip()
    for child in node:
        if _local(child.tag) == "guid" and (child.text or "").strip().startswith("http"):
            return child.text.strip()  # type: ignore[union-attr]
    return fallback


def _published_raw(node: ElementTree.Element) -> str | None:
    return _first_text(node, ("pubdate", "published", "updated", "dc:date", "date"))


def parse_feed(payload: bytes) -> list[FeedEntry]:
    """解析 feed 字节。解析失败抛 `FeedParseError`（受控，不含原始内容）。"""
    if not payload:
        raise FeedParseError("EMPTY_FEED")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise FeedParseError("MALFORMED_FEED") from error

    entries: list[FeedEntry] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = _first_text(node, ("title",))
        url = _link(node)
        if not title or not url:
            continue
        entries.append(
            FeedEntry(
                title=title,
                url=url,
                published_raw=_published_raw(node),
                summary_raw=_first_text(node, ("description", "summary", "content")),
            )
        )
        if len(entries) >= MAX_ENTRIES_PER_FEED:
            break
    return entries


def coerce_feed_timestamp(raw: str | None) -> object:
    """把 feed 里的时间字符串交给 `coerce_published_at` 处理。

    RFC 822（RSS 常见）先转成 datetime，ISO 8601 原样返回；解析不出就返回 None，
    由校验层按「核实不到」处理。
    """
    if not raw:
        return None
    text = raw.strip()
    if "," in text or text.endswith(("GMT", "UTC")):
        try:
            return parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return text


__all__ = [
    "MAX_ENTRIES_PER_FEED",
    "FeedEntry",
    "FeedParseError",
    "coerce_feed_timestamp",
    "parse_feed",
]