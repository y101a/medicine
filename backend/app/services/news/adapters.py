"""来源适配器：把各来源的机器可读报文转成候选条目。

**只做结构化解析**：不写摘要（不转存来源摘要字段、不镜像正文），不翻译，不做医学加工。
"""

import json
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.services.news.feeds import FeedEntry, FeedParseError, parse_feed

WHO_DON_ITEM_URL = "https://www.who.int/emergencies/disease-outbreak-news/item/{slug}"
WHO_NEWS_ITEM_URL = "https://www.who.int/news/item/{slug}"
# 综合新闻稿并不等于疾病资讯。只用原标题做保守筛选；未命中时宁可不入疾病专区。
_DISEASE_NEWS_TITLE = re.compile(
    r"\b(?:disease|infection|infectious|outbreak|epidemic|pandemic|"
    r"vaccin(?:e|es|ation|ations)|immuni[sz]ation|virus|viral|"
    r"cancer|tumou?r|diabetes|tuberculosis|malaria|measles|cholera|"
    r"influenza|covid(?:-19)?|hiv|aids|ebola|dengue|polio|hepatitis|"
    r"antimicrobial resistance)\b",
    re.IGNORECASE,
)


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
    return [
        entry
        for entry in _parse_who_odata(payload, item_url=WHO_NEWS_ITEM_URL)
        if _DISEASE_NEWS_TITLE.search(entry.title)
    ]


class _WhoZhNewsParser(HTMLParser):
    """只读取 WHO 中文媒体中心列表卡片；不读取图片、摘要和正文。"""

    _PATH = re.compile(r"^/zh/news/item/[a-z0-9-]+$")
    _DATE = re.compile(r"^(20\d{2})年(\d{1,2})月(\d{1,2})日$")
    _DISEASE = re.compile(
        r"疾病|疫情|传染|病毒|流感|疫苗|免疫|癌症|肿瘤|糖尿病|结核|疟疾|"
        r"霍乱|麻疹|脊灰|埃博拉|登革热|肝炎|艾滋病|抗微生物药物耐药|大流行"
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[FeedEntry] = []
        self._in_card = False
        self._section: str | None = None
        self._url: str | None = None
        self._title: list[str] = []
        self._date: list[str] = []
        self._seen_card = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        classes = (attrs_map.get("class") or "").split()
        if tag == "a" and "link-container" in classes and not self._in_card:
            candidate = urljoin("https://www.who.int/", attrs_map.get("href") or "")
            parts = urlsplit(candidate)
            if (
                parts.scheme == "https"
                and parts.hostname == "www.who.int"
                and self._PATH.fullmatch(parts.path)
            ):
                self._in_card = True
                self._seen_card = True
                self._url = candidate
                self._title = []
                self._date = []
        elif self._in_card and tag == "span" and "timestamp" in classes:
            self._section = "date"
        elif self._in_card and tag == "p" and "heading" in classes:
            self._section = "title"

    def handle_data(self, data: str) -> None:
        if self._section == "date":
            self._date.append(data)
        elif self._section == "title":
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("span", "p"):
            self._section = None
        if tag != "a" or not self._in_card:
            return
        title = " ".join(" ".join(self._title).split())
        match = self._DATE.fullmatch("".join(self._date).strip())
        if self._url and title and match and self._DISEASE.search(title):
            try:
                published = datetime(
                    int(match.group(1)), int(match.group(2)), int(match.group(3))
                ).date().isoformat()
            except ValueError:
                published = None
            if published:
                self.entries.append(
                    FeedEntry(
                        title=title,
                        url=self._url,
                        published_raw=published,
                        summary_raw=None,
                        category="disease",
                    )
                )
        self._in_card = False
        self._section = None


def parse_who_zh_news(payload: bytes) -> list[FeedEntry]:
    if not payload:
        raise FeedParseError("EMPTY_FEED")
    parser = _WhoZhNewsParser()
    try:
        parser.feed(payload.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as error:
        raise FeedParseError("MALFORMED_FEED") from error
    if not parser._seen_card:
        raise FeedParseError("NO_ENTRIES")
    return parser.entries[:200]


class _BeijingWjwParser(HTMLParser):
    """北京卫健委新闻发布列表：只保留科普标题、显示日期和本站文章链接。"""

    _ARTICLE_PATH = re.compile(r"^/xwzx_20031/xwfb/20\d{4}/t20\d{6}_\d+\.html$")
    _DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
    _EXCLUDE = re.compile(
        r"招标|采购|招聘|人事|巡察|公示|遴选|任免|表彰|奖章|获奖|服贸会|"
        r"成果发布|正式启幕|活动在京举行|项目申报|会议召开|名单发布"
    )
    _MEDICATION = re.compile(r"用药|药品|药物|药械|医疗器械|不良反应|药品安全")
    _DISEASE = re.compile(
        r"疾病|防治|预防|防护|感染|传染|病毒|流感|疫苗|接种|免疫规划|"
        r"过敏|花粉|热射病|中暑|艾滋|结核|登革热|癌症|肿瘤|汉坦"
    )
    _WELLNESS = re.compile(
        r"健康提示|养生|饮食|营养|食养|膳食|食品安全|体重|减肥|"
        r"健康度夏|健康过节|健康过假期|消暑|成长小贴士"
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[FeedEntry] = []
        self._card_depth = 0
        self._seen_card = False
        self._url: str | None = None
        self._title_attr = ""
        self._title_fallback: list[str] = []
        self._date_text: list[str] = []
        self._section: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        classes = (attrs_map.get("class") or "").split()
        if tag == "div":
            if not self._card_depth and "weinei_left_con_line" in classes:
                self._card_depth = 1
                self._seen_card = True
                self._url = None
                self._title_attr = ""
                self._title_fallback = []
                self._date_text = []
            elif self._card_depth:
                self._card_depth += 1
                if "weinei_left_con_line_date" in classes:
                    self._section = "date"
            return
        if not self._card_depth:
            return
        if tag == "a" and self._url is None:
            candidate = urljoin(
                "https://wjw.beijing.gov.cn/xwzx_20031/xwfb/", attrs_map.get("href") or ""
            )
            parts = urlsplit(candidate)
            if (
                parts.scheme == "https"
                and parts.hostname == "wjw.beijing.gov.cn"
                and self._ARTICLE_PATH.fullmatch(parts.path)
                and not parts.query
                and not parts.fragment
            ):
                self._url = candidate
                self._title_attr = (attrs_map.get("title") or "").strip()
        elif tag == "span" and self._url and "pc-hide" in classes:
            self._section = "title"

    def handle_data(self, data: str) -> None:
        if self._section == "date":
            self._date_text.append(data)
        elif self._section == "title":
            self._title_fallback.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._section == "title":
            self._section = None
        if tag != "div" or not self._card_depth:
            return
        if self._section == "date":
            self._section = None
        self._card_depth -= 1
        if self._card_depth:
            return
        title = " ".join((self._title_attr or " ".join(self._title_fallback)).split())
        date = "".join(self._date_text).strip()
        if not self._url or not title or not self._DATE.fullmatch(date):
            return
        try:
            datetime.fromisoformat(date)
        except ValueError:
            return
        if self._EXCLUDE.search(title):
            return
        if self._MEDICATION.search(title):
            category = "medication"
        elif self._DISEASE.search(title):
            category = "disease"
        elif self._WELLNESS.search(title):
            category = "wellness"
        else:
            return
        self.entries.append(
            FeedEntry(
                title=title,
                url=self._url,
                published_raw=date,
                summary_raw=None,
                category=category,
            )
        )


def parse_beijing_wjw_health(payload: bytes) -> list[FeedEntry]:
    if not payload:
        raise FeedParseError("EMPTY_FEED")
    parser = _BeijingWjwParser()
    try:
        parser.feed(payload.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as error:
        raise FeedParseError("MALFORMED_FEED") from error
    if not parser._seen_card:
        raise FeedParseError("NO_ENTRIES")
    return parser.entries[:200]


def parse_ecdc_news(payload: bytes) -> list[FeedEntry]:
    """ECDC RSS：仅保留原题、原文链接和发布时间，不转载 feed 摘要。"""
    entries = parse_feed(payload)
    for entry in entries:
        entry.summary_raw = None
    return entries


_FDA_DRUG_TITLE = re.compile(
    r"\b(?:fda (?:approves?|warns?|alerts?)|drug safety|medication|recall|"
    r"drug shortage|first (?:drug|treatment|therapy)|hidden drug ingredient)\b",
    re.IGNORECASE,
)


def parse_fda_drug_updates(payload: bytes) -> list[FeedEntry]:
    """FDA 药物 RSS 混有技术/行政更新；仅收同域药物审批、安全或召回资讯。"""
    entries: list[FeedEntry] = []
    for entry in parse_feed(payload):
        parts = urlsplit(entry.url)
        if parts.scheme not in ("http", "https") or parts.hostname != "www.fda.gov":
            continue
        if not parts.path.startswith(("/drugs/", "/safety/")):
            continue
        if not _FDA_DRUG_TITLE.search(entry.title):
            continue
        entry.url = parts._replace(scheme="https", netloc="www.fda.gov").geturl()
        entry.summary_raw = None
        # FDA RSS 的时区缩写不是 RFC 822 数值偏移；先规范化，避免把 EDT 当 UTC。
        if entry.published_raw:
            entry.published_raw = (
                entry.published_raw.replace(" EDT", " -0400").replace(" EST", " -0500")
            )
        entries.append(entry)
    return entries


class _OdphpTopicParser(HTMLParser):
    """只读 ODPHP 专题页 article teaser 的标题、日期与同域文章链接。"""

    _ARTICLE_PATH = re.compile(r"^/news/20\d{4}/[a-z0-9-]+$")
    _DATE = re.compile(r"Posted on ([A-Z][a-z]+ \d{1,2}, 20\d{2}) by ODPHP")
    _FITNESS = re.compile(
        r"\b(?:physical activity|fitness|exercise|active|move your way|sports?|"
        r"moving|workout|walking|running|muscle)\b",
        re.IGNORECASE,
    )
    _WELLNESS = re.compile(
        r"\b(?:nutrition|nutritious|diet(?:ary)?|healthy eat(?:ing)?|food|meal|"
        r"weight management)\b",
        re.IGNORECASE,
    )

    def __init__(self, category: str) -> None:
        super().__init__(convert_charrefs=True)
        self.category = category
        self.entries: list[FeedEntry] = []
        self._article_depth = 0
        self._section: str | None = None
        self._url: str | None = None
        self._title: list[str] = []
        self._date: list[str] = []
        self._seen_teaser = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "article":
            self._article_depth += 1
            if self._article_depth == 1:
                self._url = None
                self._title = []
                self._date = []
            return
        if not self._article_depth:
            return
        classes = (attrs_map.get("class") or "").split()
        if tag == "a" and "c-teaser__link" in classes:
            candidate = urljoin("https://odphp.health.gov/", attrs_map.get("href") or "")
            parts = urlsplit(candidate)
            if (
                parts.scheme == "https"
                and parts.hostname == "odphp.health.gov"
                and self._ARTICLE_PATH.fullmatch(parts.path)
            ):
                self._url = candidate
                self._section = "title"
                self._seen_teaser = True
        elif tag == "p" and "node__submitted" in classes:
            self._section = "date"

    def handle_data(self, data: str) -> None:
        if self._section == "title":
            self._title.append(data)
        elif self._section == "date":
            self._date.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "p"):
            self._section = None
        if tag != "article" or not self._article_depth:
            return
        self._article_depth -= 1
        if self._article_depth:
            return
        title = " ".join(" ".join(self._title).split())
        match = self._DATE.search(" ".join(self._date))
        relevant = self._FITNESS if self.category == "fitness" else self._WELLNESS
        if self._url and title and match and relevant.search(title):
            try:
                published = datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()
            except ValueError:
                return
            self.entries.append(
                FeedEntry(
                    title=title,
                    url=self._url,
                    published_raw=published,
                    summary_raw=None,
                    category=self.category,
                )
            )


def _parse_odphp_topic(payload: bytes, *, category: str) -> list[FeedEntry]:
    if not payload:
        raise FeedParseError("EMPTY_FEED")
    parser = _OdphpTopicParser(category)
    try:
        parser.feed(payload.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as error:
        raise FeedParseError("MALFORMED_FEED") from error
    if not parser._seen_teaser:
        raise FeedParseError("NO_ENTRIES")
    return parser.entries[:200]


def parse_odphp_fitness(payload: bytes) -> list[FeedEntry]:
    return _parse_odphp_topic(payload, category="fitness")


def parse_odphp_nutrition(payload: bytes) -> list[FeedEntry]:
    return _parse_odphp_topic(payload, category="wellness")


class _NmpaicListParser(HTMLParser):
    """只接受信息中心要闻列表中同域的静态文章链接。"""

    _ARTICLE_PATH = re.compile(r"^/yjzxyw/20\d{4}/t20\d{6}_\d+\.html$")
    _DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[FeedEntry] = []
        self._li_depth = 0
        self._href: str | None = None
        self._title: list[str] = []
        self._date: list[str] = []
        self._in_span = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "li":
            self._li_depth += 1
            if self._li_depth == 1:
                self._href = None
                self._title = []
                self._date = []
        elif self._li_depth and tag == "a" and self._href is None:
            href = attrs_map.get("href") or ""
            url = urljoin("https://www.nmpaic.org.cn/yjzxyw/", href)
            parts = urlsplit(url)
            if parts.scheme == "https" and parts.hostname == "www.nmpaic.org.cn":
                if self._ARTICLE_PATH.fullmatch(parts.path):
                    self._href = url
        elif self._li_depth and tag == "span":
            self._in_span = True

    def handle_data(self, data: str) -> None:
        if not self._li_depth:
            return
        if self._in_span:
            self._date.append(data)
        elif self._href:
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._in_span = False
        if tag != "li" or not self._li_depth:
            return
        self._li_depth -= 1
        if self._li_depth:
            return
        title = " ".join(" ".join(self._title).split())
        date = "".join(self._date).strip()
        if self._href and title and self._DATE.fullmatch(date):
            self.entries.append(
                FeedEntry(title=title, url=self._href, published_raw=date, summary_raw=None)
            )


def parse_nmpaic_news(payload: bytes) -> list[FeedEntry]:
    """药监信息中心静态列表；只收原题、本站原文链接与日期。"""
    if not payload:
        raise FeedParseError("EMPTY_FEED")
    parser = _NmpaicListParser()
    try:
        parser.feed(payload.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as error:
        raise FeedParseError("MALFORMED_FEED") from error
    if not parser.entries:
        raise FeedParseError("NO_ENTRIES")
    return parser.entries[:200]


class _ChinaNutriListParser(HTMLParser):
    """营养所科普列表的专用解析；只读取列表锚点，不访问文章正文。"""

    _ARTICLE_PATH = re.compile(
        r"^/yyjkzxpt/yyjkkpzx/hdjl/20\d{4}/t20\d{6}_\d+\.html$"
    )
    _DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
    _FITNESS = re.compile(r"运动|锻炼|健身|身体活动|肌肉|肌少")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[FeedEntry] = []
        self._url: str | None = None
        self._section: str | None = None
        self._title: list[str] = []
        self._date: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "a" and self._url is None:
            candidate = urljoin(
                "https://www.chinanutri.cn/yyjkzxpt/yyjkkpzx/hdjl/",
                attrs_map.get("href") or "",
            )
            parts = urlsplit(candidate)
            if (parts.scheme, parts.hostname) == ("https", "www.chinanutri.cn"):
                if self._ARTICLE_PATH.fullmatch(parts.path):
                    self._url = candidate
                    self._title = []
                    self._date = []
        elif tag == "div" and self._url:
            classes = (attrs_map.get("class") or "").split()
            if "fl" in classes:
                self._section = "title"
            elif "right" in classes:
                self._section = "date"

    def handle_data(self, data: str) -> None:
        if self._section == "title":
            self._title.append(data)
        elif self._section == "date":
            self._date.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            self._section = None
        elif tag == "a" and self._url:
            title = " ".join(" ".join(self._title).lstrip("> ").split())
            date = "".join(self._date).strip()
            if title and self._DATE.fullmatch(date):
                self.entries.append(
                    FeedEntry(
                        title=title,
                        url=self._url,
                        published_raw=date,
                        summary_raw=None,
                        category="fitness" if self._FITNESS.search(title) else "wellness",
                    )
                )
            self._url = None
            self._section = None


def parse_chinanutri_education(payload: bytes) -> list[FeedEntry]:
    """营养所科普栏目候选：取中文原标题、日期和同域原文链接。"""
    if not payload:
        raise FeedParseError("EMPTY_FEED")
    parser = _ChinaNutriListParser()
    try:
        parser.feed(payload.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as error:
        raise FeedParseError("MALFORMED_FEED") from error
    if not parser.entries:
        raise FeedParseError("NO_ENTRIES")
    return parser.entries[:200]


#: 有专用适配器的来源；其余按 `fetch_mode` 走通用 RSS/Atom 解析。
_PARSERS = {
    "who_disease_outbreak_news": parse_who_outbreak_news,
    "who_news_releases": parse_who_news_releases,
    "who_zh_news": parse_who_zh_news,
    "beijing_wjw_health": parse_beijing_wjw_health,
    "ecdc_news": parse_ecdc_news,
    "nmpaic_news": parse_nmpaic_news,
    "chinanutri_health_education": parse_chinanutri_education,
    "odphp_physical_activity": parse_odphp_fitness,
    "odphp_food_nutrition": parse_odphp_nutrition,
    "fda_drug_updates": parse_fda_drug_updates,
}


def parse_for_source(source_id: str, payload: bytes, *, fetch_mode: str) -> list[FeedEntry]:
    parser = _PARSERS.get(source_id)
    if parser is not None:
        return parser(payload)
    if fetch_mode in ("rss", "atom"):
        return parse_feed(payload)
    raise FeedParseError("NO_ADAPTER")
