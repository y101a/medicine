"""Validate generated Office Open XML files before encrypted storage."""

from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from docx import Document
from pptx import Presentation

from app.core.errors import AppError

_MAX_ENTRIES = 800
_MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
_FORBIDDEN_PARTS = (
    "vbaproject.bin",
    "activex/",
    "embeddings/",
    "oleobject",
)


def validate_generated_document(content: bytes, format: str, *, max_bytes: int) -> None:
    if not content or len(content) > max_bytes:
        raise AppError(500, "DOCUMENT_RENDER_FAILED", "生成文件大小不符合限制")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > _MAX_ENTRIES:
                raise ValueError("invalid entry count")
            total = 0
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                path = PurePosixPath(name)
                lower = name.lower()
                if path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
                    raise ValueError("unsafe archive path")
                if any(part in lower for part in _FORBIDDEN_PARTS):
                    raise ValueError("forbidden OOXML part")
                total += entry.file_size
                if total > _MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("archive too large")
                if (
                    entry.compress_size
                    and entry.file_size / entry.compress_size > _MAX_COMPRESSION_RATIO
                ):
                    raise ValueError("suspicious compression ratio")
                if lower.endswith(".rels"):
                    relation = archive.read(entry)
                    if b'TargetMode="External"' in relation or b"TargetMode='External'" in relation:
                        raise ValueError("external relationships are not allowed")
            names = {item.filename for item in entries}
            if "[Content_Types].xml" not in names:
                raise ValueError("missing content types")
    except (BadZipFile, KeyError, OSError, ValueError) as exc:
        raise AppError(500, "DOCUMENT_RENDER_FAILED", "生成文件未通过安全校验") from exc
    try:
        if format == "docx":
            Document(BytesIO(content))
        elif format == "pptx":
            Presentation(BytesIO(content))
        else:
            raise ValueError("unsupported format")
    except Exception as exc:
        raise AppError(500, "DOCUMENT_RENDER_FAILED", "生成文件无法重新打开校验") from exc
