"""全量投影的准入、撤回和固定模板测试（不依赖 Neo4j 服务）。"""

from test_knowledge_graph_review_publish import approve_all_candidates, extracted_fixture

from app.rag.knowledge_classification import KnowledgeClassification
from app.services.knowledge_graph_neo4j import (
    DELETE_SNAPSHOT,
    Neo4jProjectionError,
    _replace_snapshot,
)
from app.services.knowledge_graph_publication import enqueue_publication, publication_status
from app.services.knowledge_graph_review import retire_claim
from app.services.knowledge_graph_snapshot import GraphSnapshot, build_snapshot


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def single(self):
        return self.row

    def consume(self):
        return None


class FakeTx:
    def __init__(self, current=None):
        self.current = current
        self.calls = []

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        return FakeResult(self.current if query.startswith("MATCH (m:PublicGraphMeta") else None)


def test_four_layer_classification_validation():
    classification = KnowledgeClassification(primary_layer="wellness_fitness", topic_key="exercise")
    assert classification.primary_layer == "wellness_fitness"
    try:
        KnowledgeClassification(
            primary_layer="disease", secondary_layers=["disease"], topic_key="headache"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("主层不得重复进入副层")


async def test_snapshot_contains_only_live_reviewed_claims(profile_context):
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    published = await enqueue_publication(db, actor="医学测试员")
    snapshot = await build_snapshot(db, revision=published.revision)
    assert len(snapshot.claims) == 5
    assert len(snapshot.evidence) >= 5
    assert all("content" not in row for row in snapshot.evidence)

    claim_id = snapshot.claims[0]["id"]
    from uuid import UUID

    await retire_claim(db, UUID(claim_id), reviewer="医学测试员", reason="复核撤回")
    status = await publication_status(db)
    assert status.expected_revision == 2
    updated = await build_snapshot(db, revision=2)
    assert claim_id not in {row["id"] for row in updated.claims}
    assert len(updated.claims) == 4


def test_full_rebuild_deletes_old_nodes_and_rejects_stale_revision():
    snapshot = GraphSnapshot(2, [], [], [])
    tx = FakeTx({"revision": 1})
    _replace_snapshot(tx, snapshot)
    assert any(query == DELETE_SNAPSHOT for query, _ in tx.calls)
    assert any("PublicGraphMeta" in query and "CREATE" in query for query, _ in tx.calls)
    assert all("UNWIND" not in query for query, _ in tx.calls)

    old_tx = FakeTx({"revision": 3})
    try:
        _replace_snapshot(old_tx, snapshot)
    except Neo4jProjectionError:
        pass
    else:
        raise AssertionError("旧 revision 不得覆盖新图")
    assert all(query != DELETE_SNAPSHOT for query, _ in old_tx.calls)
