import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.session import SessionLocal, engine
from app.models import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.markdown_importer import (
    ControlledImportError,
    DocumentReviewMetadata,
    _enforce_source_ingestion_policy,
    import_markdown_document,
)
from app.rag.source_sync import sync_approved_sources


@pytest.fixture(autouse=True)
async def dispose_database_engine():
    yield
    await engine.dispose()


def registry_payload(source_key: str, *, approved: bool = True) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "reviewed_at": "2026-09-11",
        "policy": {
            "approved_for_ingestion": [source_key] if approved else [],
        },
        "sources": [
            {
                "id": source_key,
                "priority": 1,
                "organization": "测试卫生机构",
                "channel_name": "测试审核渠道",
                "authority_level": "test_authority",
                "jurisdiction": "CN",
                "language": "zh-CN",
                "entry_url": "https://www.nhc.gov.cn/test/index.shtml",
                "ingestion_status": "approved_for_test",
            }
        ],
    }


def review_metadata(source_key: str) -> dict[str, object]:
    return {
        "source_key": source_key,
        "canonical_url": "https://www.nhc.gov.cn/test/reviewed-article.shtml",
        "title": "已审核健康科普测试文档",
        "responsible_department": "测试部门",
        "authors": ["测试作者"],
        "published_at": "2024-05-30T00:00:00+08:00",
        "version_label": "v1",
        "license_type": "test_permission",
        "license_notes": "仅供自动化测试",
        "legal_reviewed_at": "2026-09-11T08:00:00+08:00",
        "legal_reviewed_by": "版权测试审核员",
        "medical_reviewed_at": "2026-09-11T08:30:00+08:00",
        "medical_reviewed_by": "医学测试审核员",
        "metadata": {"topic": "test"},
    }


def summary_only_source() -> KnowledgeSource:
    return KnowledgeSource(
        source_metadata={
            "ingestion_policy": {
                "allowed_content_modes": ["original_summary"],
                "max_content_chars": 200,
                "max_verbatim_quotes": 1,
                "max_verbatim_quote_chars_each": 12,
                "max_verbatim_quote_chars_total": 12,
                "require_source_attribution": True,
            }
        }
    )


def summary_metadata() -> DocumentReviewMetadata:
    payload = review_metadata("summary_source")
    payload["content_mode"] = "original_summary"
    payload["verbatim_quotes"] = ["及时就医"]
    return DocumentReviewMetadata.model_validate(payload)


def test_summary_only_policy_accepts_short_attributed_excerpt():
    _enforce_source_ingestion_policy(
        "这是项目自编摘要。危险表现需要及时就医。",
        summary_metadata(),
        summary_only_source(),
    )


def test_summary_only_policy_rejects_full_text_mode():
    payload = review_metadata("summary_source")
    metadata = DocumentReviewMetadata.model_validate(payload)

    with pytest.raises(ControlledImportError, match="内容形式"):
        _enforce_source_ingestion_policy("原始资料正文", metadata, summary_only_source())


def test_summary_only_policy_rejects_oversized_or_untracked_quotes():
    payload = review_metadata("summary_source")
    payload["content_mode"] = "original_summary"
    payload["verbatim_quotes"] = ["这是一条明显超过十二个字符的逐字引用"]
    oversized = DocumentReviewMetadata.model_validate(payload)
    with pytest.raises(ControlledImportError, match="单条逐字短引用"):
        _enforce_source_ingestion_policy(
            "这是一条明显超过十二个字符的逐字引用",
            oversized,
            summary_only_source(),
        )

    payload["verbatim_quotes"] = ["及时就医"]
    missing = DocumentReviewMetadata.model_validate(payload)
    with pytest.raises(ControlledImportError, match="原样出现在"):
        _enforce_source_ingestion_policy("这是项目自编摘要。", missing, summary_only_source())


async def test_sync_and_versioned_markdown_import_are_controlled(tmp_path):
    source_key = f"test_source_{uuid4().hex[:12]}"
    registry_path = tmp_path / "registry.json"
    markdown_path = tmp_path / "article.md"
    metadata_path = tmp_path / "article.metadata.json"
    registry_path.write_text(
        json.dumps(registry_payload(source_key), ensure_ascii=False), encoding="utf-8"
    )
    markdown_path.write_text(
        "# 健康主题\n\n这是经过审核的概述。\n\n## 何时就医\n\n出现危险表现时及时就医。",
        encoding="utf-8",
    )
    metadata = review_metadata(source_key)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    try:
        async with SessionLocal() as db:
            sync_result = await sync_approved_sources(db, registry_path)
            await db.commit()
        assert sync_result.created == 1
        assert sync_result.source_keys == (source_key,)

        async with SessionLocal() as db:
            first = await import_markdown_document(db, markdown_path, metadata_path)
            await db.commit()
        assert first.duplicate is False
        assert first.chunk_count == 2

        async with SessionLocal() as db:
            duplicate = await import_markdown_document(db, markdown_path, metadata_path)
            await db.commit()
        assert duplicate.duplicate is True
        assert duplicate.document_id == first.document_id

        markdown_path.write_text(
            "# 健康主题\n\n这是经过审核的新版概述。\n\n## 何时就医\n\n出现危险表现时立即就医。",
            encoding="utf-8",
        )
        metadata["version_label"] = "v2"
        metadata["medical_reviewed_at"] = datetime.now(UTC).isoformat()
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

        async with SessionLocal() as db:
            second = await import_markdown_document(db, markdown_path, metadata_path)
            await db.commit()
        assert second.duplicate is False
        assert second.document_id != first.document_id
        assert second.supersedes_document_id == first.document_id

        async with SessionLocal() as db:
            documents = list(
                await db.scalars(
                    select(KnowledgeDocument)
                    .join(KnowledgeSource)
                    .where(KnowledgeSource.source_key == source_key)
                    .order_by(KnowledgeDocument.created_at)
                )
            )
            chunks = list(
                await db.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == second.document_id)
                    .order_by(KnowledgeChunk.chunk_index)
                )
            )
        assert [document.review_status for document in documents] == [
            "superseded",
            "approved",
        ]
        assert documents[-1].legal_reviewed_by == "版权测试审核员"
        assert documents[-1].medical_reviewed_by == "医学测试审核员"
        assert [chunk.section_title for chunk in chunks] == ["健康主题", "何时就医"]
    finally:
        async with SessionLocal() as db:
            source_id = await db.scalar(
                select(KnowledgeSource.id).where(KnowledgeSource.source_key == source_key)
            )
            if source_id is not None:
                await db.execute(delete(IngestionJob).where(IngestionJob.source_id == source_id))
                await db.execute(
                    delete(KnowledgeDocument).where(KnowledgeDocument.source_id == source_id)
                )
                await db.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
                await db.commit()


async def test_sync_does_not_create_unapproved_source(tmp_path):
    source_key = f"test_source_{uuid4().hex[:12]}"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(registry_payload(source_key, approved=False), ensure_ascii=False),
        encoding="utf-8",
    )

    async with SessionLocal() as db:
        result = await sync_approved_sources(db, registry_path)
        await db.commit()
    assert result.approved_requested == 0
    assert result.created == 0

    async with SessionLocal() as db:
        source = await db.scalar(
            select(KnowledgeSource).where(KnowledgeSource.source_key == source_key)
        )
    assert source is None


async def test_import_rejects_interactive_html_before_database_write(tmp_path):
    markdown_path = tmp_path / "unsafe.md"
    metadata_path = tmp_path / "unsafe.metadata.json"
    markdown_path.write_text("# 标题\n\n<script>alert('x')</script>", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    async with SessionLocal() as db:
        with pytest.raises(ControlledImportError, match="HTML"):
            await import_markdown_document(db, markdown_path, metadata_path)


async def test_failed_database_import_keeps_audit_but_no_document(tmp_path):
    source_key = f"test_source_{uuid4().hex[:12]}"
    registry_path = tmp_path / "registry.json"
    markdown_path = tmp_path / "too-long-heading.md"
    metadata_path = tmp_path / "too-long-heading.metadata.json"
    registry_path.write_text(
        json.dumps(registry_payload(source_key), ensure_ascii=False), encoding="utf-8"
    )
    markdown_path.write_text(f"# {'超' * 501}\n\n已审核正文。", encoding="utf-8")
    metadata_path.write_text(
        json.dumps(review_metadata(source_key), ensure_ascii=False), encoding="utf-8"
    )

    try:
        async with SessionLocal() as db:
            await sync_approved_sources(db, registry_path)
            await db.commit()

        async with SessionLocal() as db:
            with pytest.raises(ControlledImportError, match="未写入任何不完整数据"):
                await import_markdown_document(db, markdown_path, metadata_path)
            await db.commit()

        async with SessionLocal() as db:
            source_id = await db.scalar(
                select(KnowledgeSource.id).where(KnowledgeSource.source_key == source_key)
            )
            document_count = len(
                list(
                    await db.scalars(
                        select(KnowledgeDocument).where(
                            KnowledgeDocument.source_id == source_id
                        )
                    )
                )
            )
            job = await db.scalar(
                select(IngestionJob).where(IngestionJob.source_id == source_id)
            )
        assert document_count == 0
        assert job is not None
        assert job.status == "failed"
        assert job.error_code == "CONTROLLED_IMPORT_FAILED"
    finally:
        async with SessionLocal() as db:
            source_id = await db.scalar(
                select(KnowledgeSource.id).where(KnowledgeSource.source_key == source_key)
            )
            if source_id is not None:
                await db.execute(delete(IngestionJob).where(IngestionJob.source_id == source_id))
                await db.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
                await db.commit()
