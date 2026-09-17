"""Real PostgreSQL/pgvector roundtrip, with all added rows rolled back."""

from math import sqrt

from sqlalchemy import select

from app.ai.graph.workflow import build_consultation_generation_graph
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.retrieval import RetrievalResult, search_knowledge
from app.rag.web_search import SOURCE_KEY, SearchHit


async def test_web_prototype_is_indexed_and_reused_without_a_second_search(monkeypatch):
    from app.rag import web_search

    assert get_settings().app_environment == "development"
    topic = "甲状腺结节"
    url = "https://www.nhc.gov.cn/prototype-roundtrip-test"
    snippet = "甲状腺结节健康知识原型搜索摘要。仅供测试知识库入库和查询向量的往返过程。"
    hits = [SearchHit("甲状腺结节测试摘要", url, snippet, "国家卫生健康委员会")]
    searches: list[str] = []
    query_vector = [1.0] + [0.0] * 1023
    # Real Chinese snippets can rank around 0.66: verify a short exact-topic
    # cached excerpt is reused without weakening other sources' threshold.
    vector = [0.66, sqrt(1 - 0.66**2)] + [0.0] * 1022

    async def fake_search(generic: str):
        searches.append(generic)
        return hits

    async def no_local_evidence(_db, _text, *, top_k):
        return RetrievalResult(False, "test", "v1", [])

    async def fake_vectorizer(db, document_id):
        chunk = await db.scalar(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
        )
        assert chunk is not None
        settings = get_settings()
        chunk.embedding = vector
        chunk.embedding_model = settings.embedding_model
        chunk.embedding_version = settings.embedding_version
        chunk.embedding_dimensions = settings.embedding_dimensions
        await db.flush()

    async def fake_embedder(_texts):
        from app.rag.embeddings import EmbeddingBatch

        return EmbeddingBatch(vectors=[query_vector], total_tokens=1)

    monkeypatch.setattr(web_search, "vectorize_document", fake_vectorizer)
    async with SessionLocal() as db:
        try:
            first = build_consultation_generation_graph(no_local_evidence, fake_search)
            result = await first.ainvoke({"user_text": f"{topic}是什么", "db": db})
            assert result["web_search_status"] == "completed"
            assert result["retrieval_items"][0]["canonical_url"] == url

            document = await db.scalar(
                select(KnowledgeDocument)
                .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
                .where(KnowledgeSource.source_key == SOURCE_KEY,
                       KnowledgeDocument.canonical_url == url)
            )
            assert document is not None
            assert document.review_status == "prototype"
            assert document.medical_reviewed_at is None
            assert document.document_metadata["production_eligible"] is False
            assert document.document_metadata["web_expires_at"]

            async def indexed_retriever(db, text, *, top_k):
                return await search_knowledge(db, text, top_k=top_k, embedder=fake_embedder)

            async def no_second_search(_topic):
                raise AssertionError("已索引的原型摘要应先从本地召回")

            second = build_consultation_generation_graph(
                indexed_retriever, no_second_search
            )
            reused = await second.ainvoke({"user_text": f"{topic}是什么", "db": db})
            assert reused["web_search_status"] == "skipped"
            assert any(item["canonical_url"] == url for item in reused["retrieval_items"])
            assert any(
                0.6 < item["similarity"] < 0.72
                for item in reused["retrieval_items"]
                if item["canonical_url"] == url
            )
            assert searches == [topic]
        finally:
            # Never persist test-only snippets to the developer's knowledge base.
            await db.rollback()
