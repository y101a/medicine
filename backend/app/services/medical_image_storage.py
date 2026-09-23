"""Envelope-encrypted storage for normalized medical images."""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive


@dataclass(frozen=True)
class StoredImage:
    storage_key: str
    key_ciphertext: str


def _root() -> Path:
    root = Path(get_settings().image_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolved_path(storage_key: str) -> Path:
    if not storage_key or Path(storage_key).is_absolute():
        raise ValueError("Invalid image storage key")
    root = _root()
    target = (root / storage_key).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Invalid image storage key")
    return target


def _store_sync(content: bytes) -> StoredImage:
    key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(12)
    encrypted = nonce + AESGCM(key).encrypt(nonce, content, b"medical-image-v1")
    token = secrets.token_hex(16)
    storage_key = f"{token[:2]}/{token}.bin"
    target = _resolved_path(storage_key)
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
    return StoredImage(
        storage_key=storage_key,
        key_ciphertext=encrypt_sensitive(base64.b64encode(key).decode("ascii")),
    )


async def store_image(content: bytes) -> StoredImage:
    try:
        return await asyncio.to_thread(_store_sync, content)
    except OSError as exc:
        raise AppError(500, "IMAGE_SAVE_FAILED", "图片保存失败，请稍后重试") from exc


def _load_sync(storage_key: str, key_ciphertext: str) -> bytes:
    try:
        payload = _resolved_path(storage_key).read_bytes()
        if len(payload) < 29:
            raise ValueError("Encrypted image is truncated")
        key = base64.b64decode(decrypt_sensitive(key_ciphertext), validate=True)
        return AESGCM(key).decrypt(payload[:12], payload[12:], b"medical-image-v1")
    except FileNotFoundError as exc:
        raise AppError(410, "IMAGE_EXPIRED", "图片已过期或已被删除") from exc
    except AppError:
        raise
    except Exception as exc:
        raise AppError(500, "IMAGE_STORAGE_CORRUPT", "图片存储校验失败") from exc


async def load_image(storage_key: str, key_ciphertext: str) -> bytes:
    return await asyncio.to_thread(_load_sync, storage_key, key_ciphertext)


def _remove_sync(storage_key: str | None) -> None:
    if not storage_key:
        return
    target = _resolved_path(storage_key)
    target.unlink(missing_ok=True)
    try:
        target.parent.rmdir()
    except OSError:
        pass


async def remove_image(storage_key: str | None) -> None:
    await asyncio.to_thread(_remove_sync, storage_key)


def _list_stored_image_keys_sync(older_than: datetime) -> list[str]:
    root = _root()
    cutoff = older_than.timestamp()
    keys: list[str] = []
    for target in root.rglob("*"):
        if target.is_symlink() or not target.is_file():
            continue
        if target.suffix not in {".bin", ".tmp"}:
            continue
        resolved = target.resolve()
        if root not in resolved.parents or target.stat().st_mtime > cutoff:
            continue
        keys.append(target.relative_to(root).as_posix())
    return keys


async def list_stored_image_keys(older_than: datetime) -> list[str]:
    return await asyncio.to_thread(_list_stored_image_keys_sync, older_than)
