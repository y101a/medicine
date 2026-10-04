"""Envelope-encrypted storage for generated educational illustrations."""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive

_AAD = b"generated-image-v1"


@dataclass(frozen=True)
class StoredGeneratedImage:
    storage_key: str
    key_ciphertext: str


def _root() -> Path:

    root = Path(get_settings().image_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(storage_key: str) -> Path:
    if not storage_key or Path(storage_key).is_absolute():
        raise ValueError("Invalid generated image storage key")
    root = _root()
    target = (root / storage_key).resolve()
    if root not in target.parents:
        raise ValueError("Invalid generated image storage key")
    return target


def _store(content: bytes) -> StoredGeneratedImage:
    key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(12)
    encrypted = nonce + AESGCM(key).encrypt(nonce, content, _AAD)
    token = secrets.token_hex(16)
    storage_key = f"generated/{token[:2]}/{token}.bin"
    target = _path(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return StoredGeneratedImage(
        storage_key=storage_key,
        key_ciphertext=encrypt_sensitive(base64.b64encode(key).decode("ascii")),
    )


async def store_generated_image(content: bytes) -> StoredGeneratedImage:
    try:
        return await asyncio.to_thread(_store, content)
    except OSError as exc:
        raise AppError(500, "IMAGE_GENERATION_SAVE_FAILED", "生成图片保存失败") from exc


def _load(storage_key: str, key_ciphertext: str) -> bytes:
    try:
        payload = _path(storage_key).read_bytes()
        if len(payload) < 29:
            raise ValueError("Encrypted image is truncated")
        key = base64.b64decode(decrypt_sensitive(key_ciphertext), validate=True)
        return AESGCM(key).decrypt(payload[:12], payload[12:], _AAD)
    except FileNotFoundError as exc:
        raise AppError(410, "GENERATED_IMAGE_EXPIRED", "生成图片已过期或已删除") from exc
    except AppError:
        raise
    except Exception as exc:
        raise AppError(500, "GENERATED_IMAGE_STORAGE_CORRUPT", "生成图片存储校验失败") from exc


async def load_generated_image(storage_key: str, key_ciphertext: str) -> bytes:
    return await asyncio.to_thread(_load, storage_key, key_ciphertext)
