"""真正出网的抓取层（N2）。

三条硬要求：
1. **连接前重做 SSRF 校验**：把主机解析成 IP 再判一次，挡住「域名解析到内网」的绕过
   （N1 的 `is_public_https_url` 只看字面量，覆盖不到这一层）。
2. 逐跳校验重定向目标，只认已支持的列表类型，限制体积与超时。
3. 只抛受控错误码，不透传异常原文与页面内容。
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from app.services.news.validation import is_public_https_url

USER_AGENT = "MedicalAssistantNewsBot/0.1 (foreground operator-run; source verification)"
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
        "text/html",  # 仅由已登记来源的专用列表适配器解析；不读取正文。
    }
)
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
DIRECT_ONLY_HOST = "wjw.beijing.gov.cn"


class FetchError(RuntimeError):
    """受控抓取失败：`code` 是写进来源状态的短码。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def assert_public_endpoint(url: str) -> None:
    if not is_public_https_url(url):
        raise FetchError("FETCH_URL_REJECTED")
    host = urlsplit(url).hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError("FETCH_DNS_FAILED") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise FetchError("FETCH_PRIVATE_ADDRESS")


async def fetch_document(
    url: str,
    *,
    timeout_seconds: float,
    max_bytes: int = MAX_BYTES,
    direct_beijing: bool = False,
) -> tuple[str, bytes]:
    """抓一个来源列表文档，返回 `(content_type, body)`；失败抛 `FetchError`。"""
    if direct_beijing and urlsplit(url).hostname != DIRECT_ONLY_HOST:
        raise FetchError("FETCH_DIRECT_NOT_ALLOWED")
    current = url
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/xml, text/xml;q=0.9",
    }
    timeout = httpx.Timeout(timeout_seconds, connect=min(4.0, timeout_seconds))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
        # 只对已准入的北京卫健委来源由调用方显式开启直连；其余来源仍遵从系统代理。
        trust_env=not direct_beijing,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if direct_beijing and urlsplit(current).hostname != DIRECT_ONLY_HOST:
                raise FetchError("FETCH_REDIRECT_INVALID")
            await assert_public_endpoint(current)
            try:
                async with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("FETCH_REDIRECT_INVALID")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise FetchError(f"FETCH_HTTP_{response.status_code}")
                    content_type = (
                        (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                    )
                    if content_type not in ALLOWED_CONTENT_TYPES:
                        raise FetchError("FETCH_UNSUPPORTED_TYPE")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError("FETCH_TOO_LARGE")
                        chunks.append(chunk)
                    return content_type, b"".join(chunks)
            except httpx.TimeoutException as exc:
                raise FetchError("FETCH_TIMEOUT") from exc
            except httpx.HTTPError as exc:
                raise FetchError("FETCH_FAILED") from exc
    raise FetchError("FETCH_TOO_MANY_REDIRECTS")
