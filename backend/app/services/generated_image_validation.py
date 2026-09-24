"""Validate provider result URLs and normalize generated images."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import socket
import warnings
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.errors import AppError


@dataclass(frozen=True)
class ValidatedGeneratedImage:
    content: bytes
    width: int
    height: int
    byte_size: int
    mime_type: str = "image/webp"


def _public_addresses(hostname: str) -> list[str]:
    return list(
        dict.fromkeys(
            item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        )
    )


async def validate_result_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".aliyuncs.com")
        or ".oss-" not in hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    try:
        addresses = await asyncio.to_thread(_public_addresses, hostname)
    except OSError as exc:
        raise AppError(
            502, "IMAGE_GENERATION_PROVIDER_UNAVAILABLE", "无法连接图片生成服务"
        ) from exc
    if not addresses:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise AppError(
                502,
                "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE",
                "图片生成服务返回异常",
            )
    return url


def _aigc_metadata(provider_code: str, content_id: str) -> bytes:
    value = json.dumps(
        {
            "AIGC": {
                "Label": "1",
                "ContentProducer": provider_code,
                "ProduceID": content_id,
                "ReservedCode1": "",
                "ContentPropagator": provider_code,
                "PropagateID": content_id,
                "ReservedCode2": "",
            }
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return b"ASCII\x00\x00\x00" + value.encode("ascii")


def _normalize(
    content: bytes,
    max_pixels: int,
    provider_code: str,
    content_id: str,
) -> ValidatedGeneratedImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as opened:
                opened.load()
                if getattr(opened, "n_frames", 1) != 1:
                    raise ValueError("animated image")
                width, height = opened.size
                if width < 512 or height < 512 or width * height > max_pixels:
                    raise ValueError("invalid dimensions")
                image = opened.convert("RGB")
                output = io.BytesIO()
                exif = Image.Exif()
                exif[37510] = _aigc_metadata(provider_code, content_id)
                image.save(
                    output,
                    format="WEBP",
                    quality=88,
                    method=6,
                    exact=False,
                    exif=exif.tobytes(),
                    xmp=b"",
                    icc_profile=b"",
                )
                normalized = output.getvalue()
                return ValidatedGeneratedImage(
                    content=normalized,
                    width=width,
                    height=height,
                    byte_size=len(normalized),
                )
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AppError(
            502,
            "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE",
            "图片生成服务返回了无效图片",
        ) from exc


async def download_generated_image(
    url: str,
    *,
    max_bytes: int,
    max_pixels: int,
    provider_code: str,
    content_id: str,
    client: httpx.AsyncClient | None = None,
) -> ValidatedGeneratedImage:
    await validate_result_url(url)
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
    try:
        response = await active.get(url, headers={"Accept": "image/*"})
    except httpx.TimeoutException as exc:
        raise AppError(504, "IMAGE_GENERATION_PROVIDER_TIMEOUT", "下载生成图片超时") from exc
    except httpx.RequestError as exc:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_UNAVAILABLE", "下载生成图片失败") from exc
    finally:
        if owns_client:
            await active.aclose()
    if response.is_redirect or not response.is_success:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_UNAVAILABLE", "下载生成图片失败")
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "生成图片超过大小限制")
    content = response.content
    if not content or len(content) > max_bytes:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "生成图片超过大小限制")
    return await asyncio.to_thread(
        _normalize,
        content,
        max_pixels,
        provider_code,
        content_id,
    )
