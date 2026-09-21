"""Validate and normalize user-supplied medical images without retaining originals."""

from __future__ import annotations

import asyncio
import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


@dataclass(frozen=True)
class NormalizedImage:
    display_name: str
    content: bytes
    byte_size: int
    width: int
    height: int
    mime_type: str = "image/webp"


def _safe_name(value: str | None) -> str:
    name = Path(value or "image").name.strip() or "image"
    return name[:120]


def _normalize_sync(
    source: bytes,
    display_name: str,
    *,
    max_pixels: int,
    max_dimension: int,
    max_bytes: int,
) -> NormalizedImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source)) as opened:
                opened.load()
                if (opened.format or "").upper() not in _ALLOWED_FORMATS:
                    raise AppError(
                        415,
                        "IMAGE_TYPE_NOT_ALLOWED",
                        "仅支持 JPEG、PNG 或 WebP 图片",
                    )
                if getattr(opened, "n_frames", 1) != 1:
                    raise AppError(
                        422,
                        "IMAGE_INVALID",
                        "暂不支持动态图，请上传单帧图片",
                    )
                width, height = opened.size
                if width < 32 or height < 32:
                    raise AppError(422, "IMAGE_INVALID", "图片尺寸不能小于 32×32")
                if width * height > max_pixels:
                    raise AppError(422, "IMAGE_INVALID", "图片像素总数超过限制")
                ratio = max(width / height, height / width)
                if ratio > 20:
                    raise AppError(422, "IMAGE_INVALID", "图片长宽比不能超过 20:1")

                image = ImageOps.exif_transpose(opened)
                if image.mode in {"RGBA", "LA"} or (
                    image.mode == "P" and "transparency" in image.info
                ):
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", rgba.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")
                image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(
                    output,
                    format="WEBP",
                    quality=82,
                    method=6,
                    exact=False,
                    exif=b"",
                    xmp=b"",
                    icc_profile=b"",
                )
                normalized = output.getvalue()
                if not normalized or len(normalized) > max_bytes:
                    raise AppError(413, "IMAGE_TOO_LARGE", "规范化后的图片仍超过 5 MB")
                return NormalizedImage(
                    display_name=display_name,
                    content=normalized,
                    byte_size=len(normalized),
                    width=image.width,
                    height=image.height,
                )
    except AppError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AppError(422, "IMAGE_INVALID", "无法读取图片或图片内容已损坏") from exc


async def normalize_image(
    upload: UploadFile,
    *,
    max_bytes: int,
    max_pixels: int,
    max_dimension: int,
) -> NormalizedImage:
    try:
        source = await upload.read(max_bytes + 1)
        if await upload.read(1):
            source += b"x"
    finally:
        await upload.close()
    if not source:
        raise AppError(422, "IMAGE_INVALID", "图片内容为空")
    if len(source) > max_bytes:
        raise AppError(413, "IMAGE_TOO_LARGE", "单张图片不能超过 5 MB")
    return await asyncio.to_thread(
        _normalize_sync,
        source,
        _safe_name(upload.filename),
        max_pixels=max_pixels,
        max_dimension=max_dimension,
        max_bytes=max_bytes,
    )