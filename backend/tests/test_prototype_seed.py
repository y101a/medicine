from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.session import engine
from app.models import KnowledgeDocument, KnowledgeSource
from app.rag.markdown_importer import chunk_markdown, load_markdown
from app.rag.prototype_seed import (
    PrototypeSeedError,
    load_manifest,
    seed_prototype_knowledge,
)


@pytest.fixture(autouse=True)
async def dispose_database_engine():
    yield
    await engine.dispose()


async def test_seed_prototype_corpus_is_labeled_and_idempotent(monkeypatch):
    # Use a unique source and roll back all writes; never delete the user's corpus.
    source_key = f"test_prototype_{uuid4().hex}"
    monkeypatch.setattr("app.rag.prototype_seed.PROTOTYPE_SOURCE_KEY", source_key)
    monkeypatch.setattr(
        "app.rag.prototype_seed.PROTOTYPE_SOURCE_URL",
        f"https://prototype.invalid/test/{source_key}",
    )
    # 数量以清单为准，避免每次扩充语料都要改这里。
    corpus_directory = Path(__file__).resolve().parents[1] / "data" / "prototype_knowledge"
    expected_documents = len(load_manifest(corpus_directory).documents)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(connection, expire_on_commit=False)
        try:
            async with sessions() as db:
                first = await seed_prototype_knowledge(db)
                await db.commit()
            assert first.created_documents == expected_documents
            assert first.duplicate_documents == 0

            async with sessions() as db:
                second = await seed_prototype_knowledge(db)
                await db.commit()
                source = await db.scalar(
                    select(KnowledgeSource).where(KnowledgeSource.source_key == source_key)
                )
                documents = list(
                    await db.scalars(
                        select(KnowledgeDocument).where(
                            KnowledgeDocument.source_id == source.id
                        )
                    )
                )
            assert second.created_documents == 0
            assert second.duplicate_documents == expected_documents
            assert source is not None and source.ingestion_status == "prototype"
            assert source.source_metadata["production_eligible"] is False
            assert len(documents) == expected_documents
            assert all(document.review_status == "prototype" for document in documents)
            assert all(document.medical_reviewed_at is None for document in documents)
            assert all(document.document_metadata["prototype_only"] for document in documents)
            assert all("body_systems" in document.document_metadata for document in documents)
        finally:
            await transaction.rollback()


async def test_seed_prototype_is_rejected_outside_development(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_environment", "production")
    with pytest.raises(PrototypeSeedError, match="development"):
        await seed_prototype_knowledge(None)


def test_prototype_manifest_uses_only_local_markdown_files():
    directory = Path(__file__).resolve().parents[1] / "data" / "prototype_knowledge"
    manifest = load_manifest(directory)

    # 清单应覆盖目录内除 README 说明外的全部 md（以后新增语料不必再改这个测试）。
    assert {entry.file for entry in manifest.documents} == {
        path.name for path in directory.glob("*.md")
    } - {"README.md"}
    assert len({entry.slug for entry in manifest.documents}) == len(manifest.documents)
    assert all((directory / entry.file).is_file() for entry in manifest.documents)
    # 人体系统批次（第 10–17 条）保持原样：每条只归一个系统、参考入口只允许 https。
    new_entries = manifest.documents[9:17]
    assert {system: sum(system in entry.body_systems for entry in new_entries)
            for system in ("respiratory", "digestive", "cardiovascular", "endocrine")} == {
        "respiratory": 2, "digestive": 2, "cardiovascular": 2, "endocrine": 2,
    }
    for entry in new_entries:
        assert len(entry.body_systems) == 1
        assert all(urlsplit(url).scheme == "https" for url in entry.reference_urls)
        content = load_markdown(directory / entry.file)
        assert "未经医学专业审核" in content
        assert len(chunk_markdown(content)) >= 2


def test_wellness_batch_is_prototype_only_and_marks_unreviewed():
    """养生健身批次：自编原型语料，正文自带「未经医学专业审核」声明与「不用于诊断或治疗」边界。"""
    directory = Path(__file__).resolve().parents[1] / "data" / "prototype_knowledge"
    manifest = load_manifest(directory)
    batches = (
        "wellness-",  # 2026-10-03 第一批：总体原则（9 篇）
        "fitness-",  # 2026-10-03 第二批：健身（≥10 篇）
        "tcm-",  # 2026-10-03 第二批：养生（≥10 篇）
    )
    per_batch = {
        prefix: [entry for entry in manifest.documents if entry.slug.startswith(prefix)]
        for prefix in batches
    }

    for prefix, entries in per_batch.items():
        assert len(entries) >= (9 if prefix == "wellness-" else 10), f"{prefix} 语料数量不足"
        for entry in entries:
            assert entry.topics, entry.slug
            assert entry.reference_urls, entry.slug
            # 官方入口允许 http（膳食指南与中医药局站点当前为 http），只要求是绝对 URL。
            assert all(urlsplit(url).scheme in {"http", "https"} for url in entry.reference_urls)
            assert entry.body_systems == [], entry.slug
            content = load_markdown(directory / entry.file)
            assert "未经医学专业审核" in content, entry.slug
            assert "不用于诊断或治疗" in content, entry.slug
            assert len(chunk_markdown(content)) >= 2, entry.slug


def test_medicine_use_source_covers_leftovers_and_stopping_early():
    """检索门槛不能靠降阈值救漏召回，语料本身要覆盖这两种常见口语表达。"""
    directory = Path(__file__).resolve().parents[1] / "data" / "prototype_knowledge"
    manifest = load_manifest(directory)
    medicine = next(entry for entry in manifest.documents if entry.slug == "medicine-use")
    content = (directory / medicine.file).read_text(encoding="utf-8")

    assert {"剩余药品", "规范用药", "自行停药"}.issubset(set(medicine.topics))
    assert "上次治疗剩下的药" in content
    assert "这次症状差不多" in content
    assert "不要因为吃了两天" in content
    assert "自行提前停药" in content
