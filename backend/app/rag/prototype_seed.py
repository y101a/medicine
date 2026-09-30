import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.markdown_importer import chunk_markdown, load_markdown

DEFAULT_PROTOTYPE_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "prototype_knowledge"
PROTOTYPE_SOURCE_KEY = "developer_prototype_knowledge"
PROTOTYPE_SOURCE_URL = "https://prototype.invalid/medical-knowledge"


class PrototypeSeedError(ValueError):
    pass


class PrototypeDocumentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    title: str = Field(min_length=2, max_length=500)
    file: str = Field(pattern=r"^[a-z0-9-]+\.md$")
    topics: list[str] = Field(min_length=1)
    reference_urls: list[str] = Field(default_factory=list)
    body_systems: list[Literal["respiratory", "digestive", "cardiovascular", "endocrine"]] = Field(
        default_factory=list
    )

    @field_validator("body_systems")
    @classmethod
    def no_duplicate_body_systems(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("人体系统分类不得重复")
        return value


class PrototypeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    documents: list[PrototypeDocumentEntry] = Field(min_length=1, max_length=50)


@dataclass(frozen=True, slots=True)
class PrototypeSeedResult:
    source_id: UUID
    created_documents: int
    duplicate_documents: int
    document_ids: tuple[UUID, ...]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_manifest(directory: Path) -> PrototypeManifest:
    try:
        payload = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifest = PrototypeManifest.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PrototypeSeedError("原型语料 manifest.json 无效") from exc
    slugs = [entry.slug for entry in manifest.documents]
    files = [entry.file for entry in manifest.documents]
    if len(slugs) != len(set(slugs)) or len(files) != len(set(files)):
        raise PrototypeSeedError("原型语料 slug 或文件名重复")
    return manifest


async def seed_prototype_knowledge(
    db: AsyncSession,
    directory: Path | None = None,
) -> PrototypeSeedResult:
    settings = get_settings()
    if settings.app_environment != "development":
        raise PrototypeSeedError("原型语料只允许在 development 环境导入")
    resolved_directory = (directory or DEFAULT_PROTOTYPE_DIRECTORY).resolve()
    manifest = load_manifest(resolved_directory)

    source = await db.scalar(
        select(KnowledgeSource).where(KnowledgeSource.source_key == PROTOTYPE_SOURCE_KEY)
    )
    if source is None:
        source = KnowledgeSource(
            source_key=PROTOTYPE_SOURCE_KEY,
            priority=9,
            organization="项目开发者",
            channel_name="个人开发原型医学语料",
            authority_level="self_authored_prototype",
            jurisdiction="CN",
            language="zh-CN",
            entry_url=PROTOTYPE_SOURCE_URL,
            ingestion_status="prototype",
            automated_collection=False,
            source_metadata={
                "prototype_only": True,
                "medical_reviewed": False,
                "production_eligible": False,
            },
        )
        db.add(source)
        await db.flush()
    elif source.ingestion_status != "prototype":
        raise PrototypeSeedError("原型来源键已被非原型来源占用")

    document_ids: list[UUID] = []
    created = 0
    duplicates = 0
    now = datetime.now(UTC)
    for entry in manifest.documents:
        content = load_markdown(resolved_directory / entry.file)
        content_hash = _sha256(content)
        canonical_url = f"{PROTOTYPE_SOURCE_URL}/{entry.slug}"
        duplicate = await db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.source_id == source.id,
                KnowledgeDocument.canonical_url == canonical_url,
                KnowledgeDocument.content_hash == content_hash,
            )
        )
        if duplicate is not None:
            # Backfill category metadata without replacing existing corpus revisions.
            if duplicate.review_status == "prototype":
                duplicate.document_metadata = {
                    **duplicate.document_metadata,
                    "body_systems": entry.body_systems,
                }
            document_ids.append(duplicate.id)
            duplicates += 1
            continue

        previous = await db.scalar(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.source_id == source.id,
                KnowledgeDocument.canonical_url == canonical_url,
                KnowledgeDocument.review_status == "prototype",
            )
            .order_by(KnowledgeDocument.created_at.desc())
            .limit(1)
        )
        if previous is not None:
            previous.review_status = "superseded"
        document = KnowledgeDocument(
            source_id=source.id,
            canonical_url=canonical_url,
            title=entry.title,
            responsible_department="个人开发原型",
            content_type="markdown",
            language="zh-CN",
            jurisdiction="CN",
            retrieved_at=now,
            version_label=manifest.version,
            review_status="prototype",
            license_type="developer_authored_prototype",
            license_notes="开发者自编测试摘要；不得作为正式医疗知识使用",
            content_hash=content_hash,
            content_text=content,
            supersedes_document_id=previous.id if previous else None,
            document_metadata={
                "prototype_only": True,
                "medical_reviewed": False,
                "production_eligible": False,
                "topics": entry.topics,
                "body_systems": entry.body_systems,
                "reference_urls": entry.reference_urls,
            },
        )
        db.add(document)
        await db.flush()
        chunks = chunk_markdown(content)
        db.add_all(
            [
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=index,
                    section_title=chunk.section_title,
                    section_path=list(chunk.section_path),
                    content=chunk.content,
                    content_hash=_sha256(chunk.content),
                    chunk_metadata={
                        "prototype_only": True,
                        "medical_reviewed": False,
                    },
                )
                for index, chunk in enumerate(chunks)
            ]
        )
        job = IngestionJob(
            idempotency_key=_sha256(f"prototype\n{canonical_url}\n{content_hash}"),
            source_id=source.id,
            document_id=document.id,
            job_type="prototype_seed",
            status="succeeded",
            input_uri=f"prototype://{entry.file}",
            parser_version="prototype-markdown-v1",
            stats={"chunk_count": len(chunks), "prototype_only": True},
            started_at=now,
            finished_at=now,
        )
        db.add(job)
        await db.flush()
        document_ids.append(document.id)
        created += 1

    return PrototypeSeedResult(
        source_id=source.id,
        created_documents=created,
        duplicate_documents=duplicates,
        document_ids=tuple(document_ids),
    )
