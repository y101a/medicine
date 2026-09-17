import os
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import AppError

MAX_AVATAR_BYTES = 3 * 1024 * 1024
MAX_AVATAR_PIXELS = 20_000_000
AVATAR_SIZE = (512, 512)
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def avatar_path(user_id: UUID) -> Path:
    storage = Path(get_settings().avatar_storage_dir).resolve()
    return storage / f"{user_id.hex}.webp"


async def save_avatar(user_id: UUID, upload: UploadFile) -> Path:
    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise AppError(415, "AVATAR_TYPE_NOT_ALLOWED", "头像仅支持 JPG、PNG 或 WebP 格式")

    content = await upload.read(MAX_AVATAR_BYTES + 1)
    await upload.close()
    if not content:
        raise AppError(422, "AVATAR_EMPTY", "请选择需要上传的头像图片")
    if len(content) > MAX_AVATAR_BYTES:
        raise AppError(413, "AVATAR_TOO_LARGE", "头像文件不能超过 3 MB")

    try:
        with Image.open(BytesIO(content)) as source:
            if source.width * source.height > MAX_AVATAR_PIXELS:
                raise AppError(422, "AVATAR_DIMENSIONS_TOO_LARGE", "头像图片分辨率过高")
            source.load()
            normalized = ImageOps.exif_transpose(source).convert("RGB")
            avatar = ImageOps.fit(normalized, AVATAR_SIZE, method=Image.Resampling.LANCZOS)
    except AppError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AppError(422, "AVATAR_INVALID", "头像图片已损坏或格式无效") from exc

    target = avatar_path(user_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with NamedTemporaryFile(
            dir=target.parent, prefix=f".{user_id.hex}-", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
        avatar.save(temporary_name, format="WEBP", quality=86, method=6)
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return target
