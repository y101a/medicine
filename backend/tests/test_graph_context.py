"""Graph relations can only reuse already-numbered, approved RAG sources."""

from types import SimpleNamespace
from uuid import uuid4

from app.ai import graph_context
from app.services.knowledge_graph_query import PublicGraphRelation, PublicGraphResult


async def test_graph_context_reuses_approved_number_only(monkeypatch):
    concept_id = uuid4()
    relation = PublicGraphRelation(
        claim_id=uuid4(),
        subject_id=concept_id,
        subject_name="测试主题",
        subject_type="topic",
        object_id=uuid4(),
        object_name="测试表现",
        object_type="symptom",
        predicate="MAY_INCLUDE_SYMPTOM",
        evidence=({"url": "https://example.org/approved", "chunkId": "approved-chunk"},),
    )

    async def concepts(_db, _query):
        return [SimpleNamespace(id=concept_id)]

    async def explore(_db, _id):
        return PublicGraphResult(True, 1, (relation,))

    monkeypatch.setattr(graph_context, "safe_search_topic", lambda _text: "测试主题")
    monkeypatch.setattr(graph_context, "find_public_concepts", concepts)
    monkeypatch.setattr(graph_context, "explore_public_graph", explore)
    citations = [
        {"canonical_url": "https://example.org/prototype", "trust_level": "prototype"},
        {
            "canonical_url": "https://example.org/approved",
            "chunk_id": "approved-chunk",
            "trust_level": "approved",
        },
    ]
    rendered, count = await graph_context.build_public_graph_context(None, "用户原话", citations)
    assert count == 1
    assert '"sourceNumbers": [2]' in rendered
    assert "用户原话" not in rendered

    citations[1]["trust_level"] = "prototype"
    rendered, count = await graph_context.build_public_graph_context(None, "用户原话", citations)
    assert rendered is None and count == 0
