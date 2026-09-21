import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from fastapi import UploadFile

from app.core.errors import AppError

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}
ERROR_STATUS = {
    "FILE_TOO_LARGE": 413,
    "FILE_TYPE_NOT_ALLOWED": 415,
    "FILE_PAGE_LIMIT": 422,
    "FILE_ENCRYPTED": 422,
    "FILE_NO_TEXT": 422,
    "FILE_TEXT_TOO_LARGE": 422,
    "FILE_ZIP_UNSAFE": 422,
    "FILE_PARSE_FAILED": 422,
}


@dataclass(frozen=True)
class ExtractedChunk:
    position: int
    locator: str
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    display_name: str
    kind: str
    byte_size: int
    page_count: int | None
    char_count: int
    preview: str
    chunks: tuple[ExtractedChunk, ...]


def _safe_display_name(filename: str | None) -> tuple[str, str]:
    raw = (filename or "").replace("\\", "/")
    name = PurePath(raw).name.strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)[:120]
    if not name or "." not in name:
        raise AppError(415, "FILE_TYPE_NOT_ALLOWED", "文件名必须包含受支持的扩展名")
    extension = PurePath(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AppError(
            415,
            "FILE_TYPE_NOT_ALLOWED",
            "仅支持 PDF、DOCX、PPTX、TXT 和 Markdown",
        )
    return name, extension


def _raise_worker_error(payload: dict[str, Any]) -> None:
    code = str(payload.get("code") or "FILE_PARSE_FAILED")
    if code not in ERROR_STATUS:
        code = "FILE_PARSE_FAILED"
    message = payload.get("message")
    if not isinstance(message, str) or not message or len(message) > 120:
        message = "文档无法解析"
    raise AppError(ERROR_STATUS[code], code, message)


def _split_sections(
    sections: list[dict[str, Any]],
    *,
    max_chunk_chars: int,
) -> tuple[ExtractedChunk, ...]:
    chunks: list[ExtractedChunk] = []
    for section in sections:
        locator = section.get("locator")
        text = section.get("text")
        if not isinstance(locator, str) or not isinstance(text, str):
            raise AppError(422, "FILE_PARSE_FAILED", "文档解析结果无效")
        locator = locator.strip()[:64] or "文档片段"
        text = text.strip()
        while text:
            if len(text) <= max_chunk_chars:
                part, text = text, ""
            else:
                boundary = max(
                    text.rfind("\n", 0, max_chunk_chars + 1),
                    text.rfind("。", 0, max_chunk_chars + 1),
                    text.rfind("；", 0, max_chunk_chars + 1),
                )
                if boundary < max_chunk_chars // 2:
                    boundary = max_chunk_chars
                else:
                    boundary += 1
                part, text = text[:boundary].strip(), text[boundary:].strip()
            if part:
                chunks.append(ExtractedChunk(len(chunks), locator, part))
    if not chunks:
        raise AppError(422, "FILE_NO_TEXT", "文档像是扫描件或没有可读取文字，暂时无法解析")
    return tuple(chunks)


def _run_worker(
    content: bytes,
    extension: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
    max_pages: int,
    max_chars: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "app.services.document_extract_worker",
        "--extension",
        extension,
        "--max-pages",
        str(max_pages),
        "--max-chars",
        str(max_chars),
        "--max-bytes",
        str(max_bytes),
    ]
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            command,
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(422, "FILE_PARSE_TIMEOUT", "文档解析超时，请缩小文件后重试") from exc
    if completed.returncode != 0 or len(completed.stdout) > max_chars * 6 + 100_000:
        raise AppError(422, "FILE_PARSE_FAILED", "文档无法解析")
    try:
        payload = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(422, "FILE_PARSE_FAILED", "文档无法解析") from exc
    if not isinstance(payload, dict):
        raise AppError(422, "FILE_PARSE_FAILED", "文档无法解析")
    return payload


async def extract_document(
    upload: UploadFile,
    *,
    max_bytes: int,
    max_pages: int,
    max_chars: int,
    max_chunk_chars: int,
    timeout_seconds: float,
) -> ExtractedDocument:
    display_name, extension = _safe_display_name(upload.filename)
    if bool(getattr(upload.file, "_rolled", False)):
        await upload.close()
        raise AppError(413, "FILE_TOO_LARGE", "单个文档不能超过 10 MB")
    try:
        content = await upload.read(max_bytes + 1)
    finally:
        await upload.close()
    if len(content) > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise AppError(413, "FILE_TOO_LARGE", f"单个文档不能超过 {limit_mb:g} MB")
    if not content:
        raise AppError(422, "FILE_PARSE_FAILED", "文档内容为空")

    payload = await asyncio.to_thread(
        _run_worker,
        content,
        extension,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        max_pages=max_pages,
        max_chars=max_chars,
    )
    if payload.get("ok") is not True:
        _raise_worker_error(payload)
    kind = payload.get("kind")
    page_count = payload.get("pageCount")
    char_count = payload.get("charCount")
    sections = payload.get("sections")
    if (
        kind not in {"pdf", "docx", "pptx", "txt", "md"}
        or not isinstance(char_count, int)
        or not 1 <= char_count <= max_chars
        or (page_count is not None and (not isinstance(page_count, int) or page_count < 1))
        or not isinstance(sections, list)
    ):
        raise AppError(422, "FILE_PARSE_FAILED", "文档解析结果无效")
    chunks = _split_sections(sections, max_chunk_chars=max_chunk_chars)
    preview_source = " ".join(chunk.text for chunk in chunks)
    preview = preview_source[:200] + ("…" if len(preview_source) > 200 else "")
    return ExtractedDocument(
        display_name=display_name,
        kind=kind,
        byte_size=len(content),
        page_count=page_count,
        char_count=char_count,
        preview=preview,
        chunks=chunks,
    )
