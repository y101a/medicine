import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.routes import knowledge as knowledge_route
from app.core.security import create_access_token
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.embeddings import EmbeddingBatch
from app.rag.retrieval import (
    RetrievalCitation,
    RetrievalError,
    RetrievalResult,
    _fusion_score,
    normalize_keyword_query,
    sanitize_retrieval_query,
    search_knowledge,
)
from app.services.auth import ACCESS_COOKIE


@pytest.fixture(autouse=True)
async def dispose_database_engine():
    yield
    await engine.dispose()


def unit_vector(index: int) -> list[float]:
    vector = [0.0] * 1024
    vector[index] = 1.0
    return vector


async def create_retrieval_fixture(source_key: str):
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        source = KnowledgeSource(
            source_key=source_key,
            priority=1,
            organization="测试卫生机构",
            channel_name="检索机制测试渠道",
            authority_level="test_authority",
            jurisdiction="CN",
            language="zh-CN",
            entry_url="https://www.nhc.gov.cn/test/index.shtml",
            ingestion_status="approved",
            automated_collection=False,
        )
        db.add(source)
        await db.flush()

        documents = []
        for index, (title, status, content_hash) in enumerate(
            [
                ("卒中识别测试资料", "approved", "d" * 64),
                ("合理用药测试资料", "approved", "e" * 64),
                ("已被替代的旧资料", "superseded", "f" * 64),
            ]
        ):
            document = KnowledgeDocument(
                source_id=source.id,
                canonical_url=f"https://www.nhc.gov.cn/test/retrieval-{index}.shtml",
                title=title,
                content_type="markdown",
                language="zh-CN",
                jurisdiction="CN",
                published_at=now,
                version_label=f"test-v{index + 1}",
                review_status=status,
                license_type="test_permission",
                legal_reviewed_at=now,
                legal_reviewed_by="版权测试员",
                medical_reviewed_at=now,
                medical_reviewed_by="医学测试员",
                content_hash=content_hash,
                content_text=f"{title}正文",
            )
            db.add(document)
            await db.flush()
            documents.append(document)

        db.add_all(
            [
                KnowledgeChunk(
                    document_id=documents[0].id,
                    chunk_index=0,
                    section_title="卒中识别",
                    content="用于验证卒中主题召回排序的隔离测试文本。",
                    content_hash="1" * 64,
                    embedding=unit_vector(0),
                    embedding_model="qwen3.7-text-embedding-flash",
                    embedding_version="2026-09-01",
                    embedding_dimensions=1024,
                ),
                KnowledgeChunk(
                    document_id=documents[1].id,
                    chunk_index=0,
                    section_title="合理用药",
                    content="用于验证合理用药主题召回排序的隔离测试文本。",
                    content_hash="2" * 64,
                    embedding=unit_vector(1),
                    embedding_model="qwen3.7-text-embedding-flash",
                    embedding_version="2026-09-01",
                    embedding_dimensions=1024,
                ),
                KnowledgeChunk(
                    document_id=documents[2].id,
                    chunk_index=0,
                    section_title="旧版内容",
                    content="该文本向量最接近查询，但文档已被替代，不应返回。",
                    content_hash="3" * 64,
                    embedding=unit_vector(0),
                    embedding_model="qwen3.7-text-embedding-flash",
                    embedding_version="2026-09-01",
                    embedding_dimensions=1024,
                ),
            ]
        )
        await db.commit()
        return source.id


async def cleanup_retrieval_fixture(source_id):
    async with SessionLocal() as db:
        await db.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.source_id == source_id)
        )
        await db.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
        await db.commit()


def test_query_sanitizer_removes_direct_identifiers():
    query, redacted = sanitize_retrieval_query(
        "我叫张三，手机号13800138000，身份证11010519491231002X，最近头痛"
    )

    assert redacted is True
    assert "张三" not in query
    assert "13800138000" not in query
    assert "11010519491231002X" not in query
    assert "头痛" in query


def test_query_sanitizer_rejects_identifier_only_input():
    with pytest.raises(RetrievalError) as error:
        sanitize_retrieval_query("13800138000")
    assert error.value.code == "RETRIEVAL_QUERY_EMPTY"


def test_keyword_query_keeps_disease_name_and_removes_question_wrappers():
    assert normalize_keyword_query("请问哮喘有什么表现？") == "哮喘"


def test_hybrid_fusion_uses_keywords_as_a_tiebreaker_without_overriding_strong_vectors():
    strong_vector_only = _fusion_score(
        keyword_score=None,
        vector_similarity=0.65,
        mode="hybrid",
    )
    weak_vector_with_keyword = _fusion_score(
        keyword_score=0.80,
        vector_similarity=0.40,
        mode="hybrid",
    )
    exact_term_with_close_vector = _fusion_score(
        keyword_score=1.0,
        vector_similarity=0.55,
        mode="hybrid",
    )
    close_vector_only = _fusion_score(
        keyword_score=None,
        vector_similarity=0.63,
        mode="hybrid",
    )

    assert strong_vector_only > weak_vector_with_keyword
    assert exact_term_with_close_vector > close_vector_only


async def test_pgvector_recall_returns_current_approved_citations():
    source_id = await create_retrieval_fixture(f"retrieval_test_{uuid4().hex[:12]}")
    embedded_queries: list[str] = []

    async def fake_embedder(texts: list[str]) -> EmbeddingBatch:
        embedded_queries.extend(texts)
        return EmbeddingBatch([unit_vector(0)], 5)

    try:
        async with SessionLocal() as db:
            result = await search_knowledge(
                db,
                "手机号13800138000，突然口角歪斜",
                top_k=5,
                embedder=fake_embedder,
            )

        assert result.query_redacted is True
        assert "13800138000" not in embedded_queries[0]
        assert [item.title for item in result.items if item.trust_level == "approved"] == [
            "卒中识别测试资料",
            "合理用药测试资料",
        ]
        assert result.items[0].similarity == 1.0
        assert result.items[0].section_title == "卒中识别"
        assert result.items[0].canonical_url.startswith("https://www.nhc.gov.cn/")
        assert all(item.title != "已被替代的旧资料" for item in result.items)
    finally:
        await cleanup_retrieval_fixture(source_id)


async def test_empty_approved_knowledge_base_does_not_send_query_to_provider(
    monkeypatch,
):
    from app.rag import retrieval

    settings = retrieval.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)

    async def unexpected_embedder(_texts: list[str]) -> EmbeddingBatch:
        raise AssertionError("空知识库不应调用外部向量服务")

    async with SessionLocal() as db:
        result = await search_knowledge(
            db,
            "普通感冒科普",
            embedder=unexpected_embedder,
        )

    assert result.items == []


async def test_keyword_recall_returns_unembedded_specific_disease(monkeypatch):
    from app.rag import retrieval

    settings = retrieval.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    source_id = uuid4()
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        source = KnowledgeSource(
            id=source_id,
            source_key=f"keyword_test_{uuid4().hex[:12]}",
            priority=1,
            organization="测试卫生机构",
            channel_name="关键词测试渠道",
            authority_level="test_authority",
            entry_url="https://www.nhc.gov.cn/test/index.shtml",
            ingestion_status="approved",
        )
        db.add(source)
        await db.flush()
        document = KnowledgeDocument(
            source_id=source_id,
            canonical_url="https://www.nhc.gov.cn/test/asthma.shtml",
            title="哮喘常见表现",
            content_type="markdown",
            review_status="approved",
            license_type="test_permission",
            legal_reviewed_at=now,
            legal_reviewed_by="版权测试员",
            medical_reviewed_at=now,
            medical_reviewed_by="医学测试员",
            content_hash="9" * 64,
            content_text="哮喘可出现反复喘息。",
        )
        db.add(document)
        await db.flush()
        db.add(
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=0,
                section_title="哮喘",
                content="哮喘可出现反复喘息、气促和胸闷。",
                content_hash="8" * 64,
            )
        )
        await db.commit()

    async def unexpected_embedder(_texts: list[str]) -> EmbeddingBatch:
        raise AssertionError("只有关键词候选时不应调用向量服务")

    try:
        async with SessionLocal() as db:
            result = await search_knowledge(
                db,
                "请问哮喘有什么表现？",
                embedder=unexpected_embedder,
            )
        assert result.items[0].title == "哮喘常见表现"
        assert result.items[0].similarity == 1.0
    finally:
        await cleanup_retrieval_fixture(source_id)


async def test_keyword_mode_never_calls_the_vector_service(monkeypatch):
    """keyword 模式必须完全不碰向量服务：既省成本，也能用于评测没有向量的语料。"""
    from app.rag import retrieval

    # 开发库里那 13 篇原型语料会一起参与召回；切到 production 才能只看见本用例的夹具。
    settings = retrieval.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    source_id = await create_retrieval_fixture(f"retrieval_mode_{uuid4().hex[:12]}")

    async def unexpected_embedder(_texts: list[str]) -> EmbeddingBatch:
        raise AssertionError("keyword 模式不应调用向量服务")

    try:
        async with SessionLocal() as db:
            result = await search_knowledge(
                db,
                "卒中识别",
                mode="keyword",
                embedder=unexpected_embedder,
            )

        assert result.mode == "keyword"
        # 只有标题/小节命中关键词的那一篇；另一篇只能靠向量召回，因此不应出现。
        assert [item.title for item in result.items] == ["卒中识别测试资料"]
        assert all(item.keyword_score is not None for item in result.items)
        assert all(item.vector_similarity is None for item in result.items)
    finally:
        await cleanup_retrieval_fixture(source_id)


async def test_vector_mode_ignores_keyword_hits_and_ranks_by_vector(monkeypatch):
    from app.rag import retrieval

    settings = retrieval.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    source_id = await create_retrieval_fixture(f"retrieval_mode_{uuid4().hex[:12]}")

    async def drug_embedder(_texts: list[str]) -> EmbeddingBatch:
        # unit_vector(1) 与「合理用药测试资料」的块向量一致：即使查询词「卒中识别」
        # 在关键词上与它毫无交集，纯向量模式下它也应排第一。
        return EmbeddingBatch([unit_vector(1)], 5)

    try:
        async with SessionLocal() as db:
            result = await search_knowledge(
                db,
                "卒中识别",
                mode="vector",
                embedder=drug_embedder,
            )

        assert result.mode == "vector"
        assert result.items[0].title == "合理用药测试资料"
        assert result.items[0].vector_similarity == 1.0
        assert all(item.keyword_score is None for item in result.items)
    finally:
        await cleanup_retrieval_fixture(source_id)


async def test_default_mode_is_hybrid_and_merges_both_paths(monkeypatch):
    """默认模式不许变：关键词与向量各召回一篇时，两篇都要在。"""
    from app.rag import retrieval

    settings = retrieval.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    source_id = await create_retrieval_fixture(f"retrieval_mode_{uuid4().hex[:12]}")

    async def drug_embedder(_texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch([unit_vector(1)], 5)

    try:
        async with SessionLocal() as db:
            result = await search_knowledge(db, "卒中识别", embedder=drug_embedder)

        assert result.mode == "hybrid"
        assert {item.title for item in result.items} == {
            "卒中识别测试资料",
            "合理用药测试资料",
        }
    finally:
        await cleanup_retrieval_fixture(source_id)


async def test_invalid_retrieval_mode_is_rejected():
    async with SessionLocal() as db:
        with pytest.raises(RetrievalError) as error:
            await search_knowledge(db, "卒中识别", mode="semantic")  # type: ignore[arg-type]

    assert error.value.code == "RETRIEVAL_MODE_INVALID"


def test_knowledge_search_api_requires_login():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/search",
            json={"query": "合理用药", "topK": 3},
        )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    asyncio.run(engine.dispose())


async def test_knowledge_search_api_returns_verifiable_citation(
    profile_context, monkeypatch
):
    client, _, (user, _) = profile_context
    chunk_id = uuid4()
    document_id = uuid4()

    async def fake_search(_db, query: str, *, top_k: int):
        assert query == "卒中识别"
        assert top_k == 3
        return RetrievalResult(
            query_redacted=False,
            model="qwen3.7-text-embedding-flash",
            version="2026-09-01",
            items=[
                RetrievalCitation(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source_key="test_source",
                    organization="测试卫生机构",
                    title="测试资料",
                    canonical_url="https://www.nhc.gov.cn/test/article.shtml",
                    section_title="卒中识别",
                    version_label="test-v1",
                    published_at=datetime(2024, 5, 30, tzinfo=UTC),
                    content="隔离测试引用内容。",
                    similarity=0.912345,
                    trust_level="approved",
                )
            ],
        )

    monkeypatch.setattr(knowledge_route, "search_knowledge", fake_search)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "卒中识别", "topK": 3},
    )

    assert response.status_code == 200
    assert response.json() == {
        "queryRedacted": False,
        "embeddingModel": "qwen3.7-text-embedding-flash",
        "embeddingVersion": "2026-09-01",
        "items": [
            {
                "chunkId": str(chunk_id),
                "documentId": str(document_id),
                "sourceKey": "test_source",
                "organization": "测试卫生机构",
                "title": "测试资料",
                "canonicalUrl": "https://www.nhc.gov.cn/test/article.shtml",
                "sectionTitle": "卒中识别",
                "versionLabel": "test-v1",
                "publishedAt": "2024-05-30T00:00:00Z",
                "content": "隔离测试引用内容。",
                "similarity": 0.912345,
                "trustLevel": "approved",
            }
        ],
    }


def test_medical_retrieval_evaluation_set_has_required_coverage():
    path = Path(__file__).resolve().parents[1] / "docs" / "medical_retrieval_evaluation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert payload["status"] == "prototype_baseline_completed"
    assert len(cases) >= payload["minimum_case_count"] >= 10
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["safety_class"] for case in cases} >= {"education", "urgent", "emergency"}
    assert all(case["query"] and case["expected_topics"] for case in cases)
    assert all(case["expected_document_slugs"] for case in cases)
    assert all(case["candidate_source_keys"] for case in cases)
