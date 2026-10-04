"""资讯条目的规范化与安全校验。**纯离线**：只用标准库，不做 DNS、不发请求。"""

import hashlib
import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_TITLE_CHARS = 300
MAX_SUMMARY_CHARS = 200
#: 追踪参数：规范化时去掉，避免同一篇文章因分享参数被当成两条。
_TRACKING_KEYS = ("utm_", "spm", "share_", "fbclid", "gclid", "yclid", "from", "source")
#: 明显不属于公网的域名后缀。
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")
#: 允许的端口：只走标准 HTTPS，避免拿来源当端口扫描器。
_ALLOWED_PORTS = {None, 443}
#: 发布时间比现在晚这么多就认为不可信，按「核实不到」处理。
_FUTURE_TOLERANCE = timedelta(days=1)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Rejection:
    """受控的拒收原因。只暴露码与短说明，不透传页面内容或异常原文。"""

    code: str
    detail: str


def normalize_canonical_url(raw: str) -> str | None:
    """规范化链接：统一 scheme/host 大小写、去追踪参数、去 fragment、去末尾斜杠。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    parts = urlsplit(raw.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_KEYS)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(query),
            "",
        )
    )


def is_public_https_url(url: str) -> bool:
    """SSRF 防护（离线部分）：只允许公网 HTTPS，拒绝本机、内网与非常规端口。

    这里**不解析 DNS**：DNS 指向内网的绕过要由真正抓取的适配器在连接时再判一次
    （N2），本函数只拦掉明显的本机/内网字面量与非标准端口。
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return False
    if "@" in parts.netloc:  # 带用户信息的 URL 一律不要
        return False
    try:
        port = parts.port
    except ValueError:
        return False
    if port not in _ALLOWED_PORTS:
        return False
    if host.endswith(_BLOCKED_HOST_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def normalize_title(title: str) -> str:
    """标题归一化：NFKC（全角转半角）、去标签、压缩空白、统一小写。"""
    text = _TAG_RE.sub(" ", title or "")
    text = _WS_RE.sub(" ", unicodedata.normalize("NFKC", text)).strip()
    return text.lower()


def title_fingerprint(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def clean_summary(raw: str | None) -> str | None:
    """摘要清洗：去标签、压空白、截断。写不出可靠摘要时返回 None（宁缺勿造）。"""
    if not raw:
        return None
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", raw)).strip()
    if not text:
        return None
    return text[:MAX_SUMMARY_CHARS]


def coerce_published_at(value: object, *, now: datetime | None = None) -> datetime | None:
    """把来源给的时间转成带时区的 UTC；解析不出或明显不可信就返回 None。

    **绝不**用抓取时间顶替：调用方另有 `first_seen_at`/`last_seen_at` 记录获取时间。
    """
    moment = now or datetime.now(UTC)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    if parsed > moment + _FUTURE_TOLERANCE:
        return None
    return parsed


def validate_entry(
    *,
    source_id: str,
    category: str,
    allowed_categories: list[str],
    title: str,
    url: str,
    published_at: object,
    summary: str | None,
    now: datetime,
) -> tuple[dict[str, object] | None, Rejection | None]:
    """校验一条候选资讯。通过返回规范化后的字段，否则返回受控拒收原因。"""
    cleaned_title = _WS_RE.sub(" ", _TAG_RE.sub(" ", title or "")).strip()
    if not cleaned_title:
        return None, Rejection("EMPTY_TITLE", "条目没有标题")
    title_text = cleaned_title[:MAX_TITLE_CHARS]

    canonical = normalize_canonical_url(url)
    if canonical is None:
        return None, Rejection("INVALID_URL", "链接不是完整网址")
    if not is_public_https_url(canonical):
        return None, Rejection("URL_NOT_PUBLIC_HTTPS", "链接不是公开 HTTPS 地址")

    if not allowed_categories:
        return None, Rejection("SOURCE_SCOPE_EMPTY", "来源未配置分类范围")
    if category not in allowed_categories:
        return None, Rejection("CATEGORY_NOT_IN_SCOPE", "分类不在该来源范围内")

    return (
        {
            "source_id": source_id,
            "category": category,
            "title": title_text,
            "summary": clean_summary(summary),
            "canonical_url": canonical,
            "published_at": coerce_published_at(published_at, now=now),
            "fingerprint": title_fingerprint(title_text),
        },
        None,
    )