"""Envelope-encrypted storage for generated DOCX/PPTX files."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive


@dataclass(frozen=True)
class StoredGeneratedDocument:
    storage_key: str
    key_ciphertext: str
    content_sha256: str


def _root() -> Path:
    root = Path(get_settings().document_generation_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(storage_key: str) -> Path:
    if not storage_key or Path(storage_key).is_absolute():
        raise ValueError("Invalid generated document storage key")
    root = _root()
    target = (root / storage_key).resolve()
    if root not in target.parents:
        raise ValueError("Invalid generated document storage key")
    return target


def _aad(generation_id: UUID, format: str) -> bytes:
    if format not in {"docx", "pptx", "pptx-template"}:
        raise ValueError("Invalid generated document format")
    return f"generated-document-v1:{generation_id}:{format}".encode("ascii")


def _store(content: bytes, generation_id: UUID, format: str) -> StoredGeneratedDocument:
    key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(12)
    encrypted = nonce + AESGCM(key).encrypt(nonce, content, _aad(generation_id, format))
    token = secrets.token_hex(16)
    prefix = "templates" if format == "pptx-template" else "files"
    storage_key = f"{prefix}/{generation_id.hex[:2]}/{token}.bin"
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
    return StoredGeneratedDocument(
        storage_key=storage_key,
        key_ciphertext=encrypt_sensitive(base64.b64encode(key).decode("ascii")),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )


async def store_generated_document(
    content: bytes,
    generation_id: UUID,
    format: str,
) -> StoredGeneratedDocument:
    try:
        return await asyncio.to_thread(_store, content, generation_id, format)
    except OSError as exc:
        raise AppError(500, "DOCUMENT_RENDER_FAILED", "生成文件保存失败") from exc


def _load(storage_key: str, key_ciphertext: str, generation_id: UUID, format: str) -> bytes:
    try:
        payload = _path(storage_key).read_bytes()
        if len(payload) < 29:
            raise ValueError("Encrypted document is truncated")
        key = base64.b64decode(decrypt_sensitive(key_ciphertext), validate=True)
        return AESGCM(key).decrypt(
            payload[:12],
            payload[12:],
            _aad(generation_id, format),
        )
    except FileNotFoundError as exc:
        raise AppError(410, "GENERATED_DOCUMENT_EXPIRED", "生成文档已过期或已删除") from exc
    except AppError:
        raise
    except Exception as exc:
        raise AppError(500, "GENERATED_DOCUMENT_STORAGE_CORRUPT", "生成文档存储校验失败") from exc


async def load_generated_document(
    storage_key: str,
    key_ciphertext: str,
    generation_id: UUID,
    format: str,
) -> bytes:
    return await asyncio.to_thread(_load, storage_key, key_ciphertext, generation_id, format)


async def remove_generated_document(storage_key: str) -> None:
    target = _path(storage_key)
    await asyncio.to_thread(target.unlink, missing_ok=True)


def _list_keys(older_than: datetime) -> list[str]:
    root = _root()
    cutoff = older_than.timestamp()
    keys: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".bin", ".tmp"}:
            continue
        try:
            if path.stat().st_mtime <= cutoff:
                keys.append(path.relative_to(root).as_posix())
        except FileNotFoundError:
            continue
    return keys


async def list_generated_document_keys(older_than: datetime) -> list[str]:
    return await asyncio.to_thread(_list_keys, older_than)
