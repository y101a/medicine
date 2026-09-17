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
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(connection, expire_on_commit=False)
        try:
            async with sessions() as db:
                first = await seed_prototype_knowledge(db)
                await db.commit()
            assert first.created_documents == 13
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
            assert second.duplicate_documents == 13
            assert source is not None and source.ingestion_status == "prototype"
            assert source.source_metadata["production_eligible"] is False
            assert len(documents) == 13
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

    assert len(manifest.documents) == 13
    assert len({entry.slug for entry in manifest.documents}) == 13
    assert all((directory / entry.file).is_file() for entry in manifest.documents)
    new_entries = manifest.documents[5:]
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
