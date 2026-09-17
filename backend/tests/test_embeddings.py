import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.embeddings import EmbeddingBatch, EmbeddingError, embed_texts, embeddings_url
from app.rag.vectorizer import ControlledVectorizationError, vectorize_document


@pytest.fixture(autouse=True)
async def dispose_database_engine():
    yield
    await engine.dispose()


def embedding_settings():
    return get_settings().model_copy(
        update={
            "qwen_api_key": SecretStr("test-key"),
            "qwen_base_url": "https://dashscope.example/compatible-mode/v1/",
            "embedding_model": "qwen3.7-text-embedding-flash",
            "embedding_dimensions": 1024,
            "embedding_batch_size": 20,
        }
    )


async def test_embedding_client_uses_openai_endpoint_and_restores_input_order():
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2] * 1024},
                    {"index": 0, "embedding": [0.1] * 1024},
                ],
                "usage": {"total_tokens": 12},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await embed_texts(
            ["第一段", "第二段"], client=client, settings=embedding_settings()
        )

    assert captured["url"] == "https://dashscope.example/compatible-mode/v1/embeddings"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"] == {
        "model": "qwen3.7-text-embedding-flash",
        "input": ["第一段", "第二段"],
        "dimensions": 1024,
        "encoding_format": "float",
    }
    assert result.vectors[0][0] == 0.1
    assert result.vectors[1][0] == 0.2
    assert result.total_tokens == 12


async def test_embedding_client_rejects_wrong_dimensions():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(EmbeddingError) as error:
            await embed_texts(["测试"], client=client, settings=embedding_settings())
    assert error.value.code == "EMBEDDING_DIMENSION_MISMATCH"


async def create_approved_document(source_key: str):
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        source = KnowledgeSource(
            source_key=source_key,
            priority=1,
            organization="测试机构",
            channel_name="测试渠道",
            authority_level="test_authority",
            jurisdiction="CN",
            language="zh-CN",
            entry_url="https://www.nhc.gov.cn/test/index.shtml",
            ingestion_status="approved",
            automated_collection=False,
        )
        db.add(source)
        await db.flush()
        document = KnowledgeDocument(
            source_id=source.id,
            canonical_url="https://www.nhc.gov.cn/test/embedding.shtml",
            title="向量化测试文档",
            content_type="markdown",
            language="zh-CN",
            jurisdiction="CN",
            review_status="approved",
            license_type="test_permission",
            legal_reviewed_at=now,
            legal_reviewed_by="版权测试员",
            medical_reviewed_at=now,
            medical_reviewed_by="医学测试员",
            content_hash="a" * 64,
            content_text="第一块。第二块。",
        )
        db.add(document)
        await db.flush()
        db.add_all(
            [
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=0,
                    content="第一块。",
                    content_hash="b" * 64,
                ),
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=1,
                    content="第二块。",
                    content_hash="c" * 64,
                ),
            ]
        )
        await db.commit()
        return source.id, document.id


async def cleanup_document(source_id):
    async with SessionLocal() as db:
        await db.execute(delete(IngestionJob).where(IngestionJob.source_id == source_id))
        await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.source_id == source_id))
        await db.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
        await db.commit()


async def test_vectorize_document_is_atomic_and_idempotent():
    source_id, document_id = await create_approved_document(
        f"embedding_test_{uuid4().hex[:12]}"
    )
    calls: list[list[str]] = []

    async def fake_embedder(texts: list[str]) -> EmbeddingBatch:
        calls.append(texts)
        return EmbeddingBatch([[float(index + 1)] * 1024 for index in range(len(texts))], 8)

    try:
        async with SessionLocal() as db:
            first = await vectorize_document(db, document_id, embedder=fake_embedder)
            await db.commit()
        assert first.duplicate is False
        assert first.chunk_count == 2
        assert first.dimensions == 1024
        assert first.total_tokens == 16
        assert calls == [["第一块。"], ["第二块。"]]

        async with SessionLocal() as db:
            second = await vectorize_document(db, document_id, embedder=fake_embedder)
            await db.commit()
        assert second.duplicate is True
        assert len(calls) == 2

        async with SessionLocal() as db:
            chunks = list(
                await db.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == document_id)
                    .order_by(KnowledgeChunk.chunk_index)
                )
            )
            job = await db.scalar(
                select(IngestionJob).where(IngestionJob.document_id == document_id)
            )
        assert all(len(chunk.embedding) == 1024 for chunk in chunks)
        assert all(chunk.embedding_model == "qwen3.7-text-embedding-flash" for chunk in chunks)
        assert all(chunk.embedding_version == "2026-09-01" for chunk in chunks)
        assert job is not None and job.status == "succeeded"
    finally:
        await cleanup_document(source_id)


async def test_vectorize_document_failure_keeps_audit_without_partial_vectors():
    source_id, document_id = await create_approved_document(
        f"embedding_test_{uuid4().hex[:12]}"
    )

    async def failing_embedder(_texts: list[str]) -> EmbeddingBatch:
        raise EmbeddingError("EMBEDDING_TIMEOUT", "阿里云向量服务响应超时")

    try:
        async with SessionLocal() as db:
            with pytest.raises(ControlledVectorizationError, match="响应超时"):
                await vectorize_document(db, document_id, embedder=failing_embedder)
            await db.commit()

        async with SessionLocal() as db:
            chunks = list(
                await db.scalars(
                    select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
                )
            )
            job = await db.scalar(
                select(IngestionJob).where(IngestionJob.document_id == document_id)
            )
        assert all(chunk.embedding is None for chunk in chunks)
        assert job is not None and job.status == "failed"
        assert job.error_code == "EMBEDDING_TIMEOUT"
    finally:
        await cleanup_document(source_id)


def test_embeddings_url_accepts_a_complete_endpoint():
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    assert embeddings_url(url) == url
