import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource

MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
DEFAULT_CHUNK_CHARS = 1000
DEFAULT_CHUNK_OVERLAP = 120
PARSER_VERSION = "markdown-section-v1"
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
DANGEROUS_HTML_PATTERN = re.compile(
    r"<\s*(?:script|iframe|object|embed|form|input|button)\b", re.IGNORECASE
)


class ControlledImportError(ValueError):
    """A safe, user-facing rejection of an untrusted import."""


class DocumentReviewMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(min_length=1, max_length=64)
    canonical_url: str
    title: str = Field(min_length=1, max_length=500)
    responsible_department: str | None = Field(default=None, max_length=200)
    authors: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    version_label: str | None = Field(default=None, max_length=100)
    license_type: str = Field(min_length=1, max_length=64)
    license_notes: str | None = None
    legal_reviewed_at: datetime
    legal_reviewed_by: str = Field(min_length=2, max_length=200)
    medical_reviewed_at: datetime
    medical_reviewed_by: str = Field(min_length=2, max_length=200)
    content_mode: Literal["licensed_full_text", "original_summary"] = "licensed_full_text"
    verbatim_quotes: list[str] = Field(default_factory=list, max_length=10)
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("canonical_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("canonical_url 必须是完整 HTTPS 地址")
        return value

    @field_validator("published_at", "legal_reviewed_at", "medical_reviewed_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("日期时间必须包含时区")
        return value


@dataclass(frozen=True, slots=True)
class MarkdownChunkData:
    section_title: str | None
    section_path: tuple[str, ...]
    content: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    document_id: UUID
    chunk_count: int
    duplicate: bool
    supersedes_document_id: UUID | None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_markdown(path: Path) -> str:
    resolved = path.resolve()
    if resolved.suffix.lower() not in {".md", ".markdown"}:
        raise ControlledImportError("只允许导入 .md 或 .markdown 文件")
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise ControlledImportError("无法读取 Markdown 文件") from exc
    if size <= 0 or size > MAX_MARKDOWN_BYTES:
        raise ControlledImportError("Markdown 文件必须大于 0 且不超过 2 MiB")
    try:
        content = resolved.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ControlledImportError("Markdown 文件必须是 UTF-8 编码") from exc
    content = unicodedata.normalize("NFKC", content).replace("\r\n", "\n").strip()
    if DANGEROUS_HTML_PATTERN.search(content):
        raise ControlledImportError("Markdown 包含不允许的可执行或交互式 HTML")
    if content.startswith("---\n"):
        marker = content.find("\n---\n", 4)
        if marker >= 0:
            content = content[marker + 5 :].strip()
    if not content:
        raise ControlledImportError("Markdown 正文不能为空")
    return content


def _load_metadata(path: Path) -> DocumentReviewMetadata:
    try:
        payload = json.loads(path.resolve().read_text(encoding="utf-8-sig"))
        metadata = DocumentReviewMetadata.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ControlledImportError("审核元数据 JSON 无效或字段不完整") from exc
    now = datetime.now(UTC) + timedelta(minutes=5)
    if metadata.legal_reviewed_at > now or metadata.medical_reviewed_at > now:
        raise ControlledImportError("审核时间不能晚于当前时间")
    return metadata


def _split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(
                text.rfind(mark, start + max_chars // 2, end)
                for mark in ("。", "！", "？", "\n", "；")
            )
            if boundary > start:
                end = boundary + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [part for part in parts if part]


def chunk_markdown(
    content: str,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[MarkdownChunkData]:
    if max_chars < 200 or overlap < 0 or overlap >= max_chars:
        raise ValueError("切块参数无效")
    heading_path: list[str] = []
    sections: list[tuple[tuple[str, ...], list[str]]] = []
    section_lines: list[str] = []

    def flush_section() -> None:
        nonlocal section_lines
        body = "\n".join(section_lines).strip()
        if body:
            sections.append((tuple(heading_path), [body]))
        section_lines = []

    for line in content.splitlines():
        heading = HEADING_PATTERN.match(line)
        if heading:
            flush_section()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_path[level - 1 :] = [title]
        else:
            section_lines.append(line.rstrip())
    flush_section()

    chunks: list[MarkdownChunkData] = []
    for path, bodies in sections:
        for body in bodies:
            paragraphs = [part.strip() for part in re.split(r"\n{2,}", body) if part.strip()]
            buffer = ""
            for paragraph in paragraphs:
                candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
                if len(candidate) <= max_chars:
                    buffer = candidate
                    continue
                if buffer:
                    chunks.append(MarkdownChunkData(path[-1] if path else None, path, buffer))
                long_parts = _split_long_text(paragraph, max_chars, overlap)
                chunks.extend(
                    MarkdownChunkData(path[-1] if path else None, path, part)
                    for part in long_parts[:-1]
                )
                buffer = long_parts[-1]
            if buffer:
                chunks.append(MarkdownChunkData(path[-1] if path else None, path, buffer))
    if not chunks:
        raise ControlledImportError("Markdown 没有可导入的正文")
    return chunks


def _same_source_domain(document_url: str, source_url: str) -> bool:
    document_host = (urlparse(document_url).hostname or "").lower()
    source_host = (urlparse(source_url).hostname or "").lower()
    return document_host == source_host or document_host.endswith(f".{source_host}")


def _policy_limit(policy: dict[str, object], key: str) -> int | None:
    value = policy.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ControlledImportError(f"来源入库策略字段 {key} 无效")
    return value


def _enforce_source_ingestion_policy(
    content: str,
    metadata: DocumentReviewMetadata,
    source: KnowledgeSource,
) -> None:
    raw_policy = (source.source_metadata or {}).get("ingestion_policy")
    if raw_policy is None:
        return
    if not isinstance(raw_policy, dict):
        raise ControlledImportError("来源入库策略格式无效")

    allowed_modes = raw_policy.get("allowed_content_modes")
    if not isinstance(allowed_modes, list) or not all(
        isinstance(mode, str) for mode in allowed_modes
    ):
        raise ControlledImportError("来源入库策略缺少 allowed_content_modes")
    if metadata.content_mode not in allowed_modes:
        raise ControlledImportError("该来源只允许自编摘要或明确获许可的内容形式")

    max_content_chars = _policy_limit(raw_policy, "max_content_chars")
    if max_content_chars is not None and len(content) > max_content_chars:
        raise ControlledImportError("自编摘要超过该来源允许的最大长度")

    quote_count = _policy_limit(raw_policy, "max_verbatim_quotes")
    quote_each = _policy_limit(raw_policy, "max_verbatim_quote_chars_each")
    quote_total = _policy_limit(raw_policy, "max_verbatim_quote_chars_total")
    quotes = metadata.verbatim_quotes
    if quote_count is not None and len(quotes) > quote_count:
        raise ControlledImportError("逐字短引用数量超过该来源限制")
    if quote_each is not None and any(len(quote) > quote_each for quote in quotes):
        raise ControlledImportError("单条逐字短引用超过该来源限制")
    if quote_total is not None and sum(map(len, quotes)) > quote_total:
        raise ControlledImportError("逐字短引用总长度超过该来源限制")
    if any(not quote.strip() or quote not in content for quote in quotes):
        raise ControlledImportError("逐字短引用必须非空且原样出现在摘要正文中")


async def import_markdown_document(
    db: AsyncSession,
    markdown_path: Path,
    metadata_path: Path,
) -> ImportResult:
    content = load_markdown(markdown_path)
    metadata = _load_metadata(metadata_path)
    content_hash = _sha256(content)
    chunks = chunk_markdown(content)

    source = await db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.source_key == metadata.source_key,
            KnowledgeSource.ingestion_status == "approved",
        )
    )
    if source is None:
        raise ControlledImportError("来源未同步或尚未批准入库")
    if not _same_source_domain(metadata.canonical_url, source.entry_url):
        raise ControlledImportError("文档 URL 与已批准来源域名不一致")
    _enforce_source_ingestion_policy(content, metadata, source)

    duplicate = await db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.source_id == source.id,
            KnowledgeDocument.canonical_url == metadata.canonical_url,
            KnowledgeDocument.content_hash == content_hash,
        )
    )
    if duplicate is not None:
        chunk_count = len(
            list(
                await db.scalars(
                    select(KnowledgeChunk).where(KnowledgeChunk.document_id == duplicate.id)
                )
            )
        )
        return ImportResult(duplicate.id, chunk_count, True, duplicate.supersedes_document_id)

    idempotency_key = _sha256(f"{metadata.source_key}\n{metadata.canonical_url}\n{content_hash}")
    job = await db.scalar(
        select(IngestionJob).where(IngestionJob.idempotency_key == idempotency_key)
    )
    now = datetime.now(UTC)
    if job is None:
        job = IngestionJob(
            idempotency_key=idempotency_key,
            source_id=source.id,
            job_type="document_import",
            status="running",
            input_uri=f"local://{markdown_path.name}",
            parser_version=PARSER_VERSION,
            started_at=now,
        )
        db.add(job)
    else:
        job.status = "running"
        job.error_code = None
        job.error_message = None
        job.started_at = now
        job.finished_at = None
    await db.flush()

    try:
        async with db.begin_nested():
            previous = await db.scalar(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.source_id == source.id,
                    KnowledgeDocument.canonical_url == metadata.canonical_url,
                    KnowledgeDocument.review_status == "approved",
                )
                .order_by(KnowledgeDocument.created_at.desc())
                .limit(1)
            )
            if previous is not None:
                previous.review_status = "superseded"

            document = KnowledgeDocument(
                source_id=source.id,
                canonical_url=metadata.canonical_url,
                title=metadata.title,
                responsible_department=metadata.responsible_department,
                authors=metadata.authors,
                content_type="markdown",
                language=source.language,
                jurisdiction=source.jurisdiction,
                published_at=metadata.published_at,
                retrieved_at=now,
                version_label=metadata.version_label,
                review_status="approved",
                license_type=metadata.license_type,
                license_notes=metadata.license_notes,
                legal_reviewed_at=metadata.legal_reviewed_at,
                legal_reviewed_by=metadata.legal_reviewed_by,
                medical_reviewed_at=metadata.medical_reviewed_at,
                medical_reviewed_by=metadata.medical_reviewed_by,
                content_hash=content_hash,
                content_text=content,
                supersedes_document_id=previous.id if previous else None,
                document_metadata={
                    **metadata.metadata,
                    "content_mode": metadata.content_mode,
                    "verbatim_quotes": metadata.verbatim_quotes,
                    "parser_version": PARSER_VERSION,
                    "source_file_name": markdown_path.name,
                },
            )
            db.add(document)
            await db.flush()
            db.add_all(
                [
                    KnowledgeChunk(
                        document_id=document.id,
                        chunk_index=index,
                        section_title=chunk.section_title,
                        section_path=list(chunk.section_path),
                        content=chunk.content,
                        content_hash=_sha256(chunk.content),
                        chunk_metadata={"parser_version": PARSER_VERSION},
                    )
                    for index, chunk in enumerate(chunks)
                ]
            )
            await db.flush()
            job.document_id = document.id
            job.status = "succeeded"
            job.stats = {
                "chunk_count": len(chunks),
                "content_characters": len(content),
                "content_hash": content_hash,
            }
            job.finished_at = datetime.now(UTC)
        await db.flush()
    except Exception as exc:
        job.status = "failed"
        job.error_code = "CONTROLLED_IMPORT_FAILED"
        job.error_message = str(exc)[:1000]
        job.finished_at = datetime.now(UTC)
        await db.flush()
        if isinstance(exc, ControlledImportError):
            raise
        raise ControlledImportError("文档导入失败，未写入任何不完整数据") from exc

    return ImportResult(
        document.id,
        len(chunks),
        False,
        previous.id if previous else None,
    )
