"""Only matching revision and currently valid PostgreSQL evidence may leave the graph API."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from test_knowledge_graph_review_publish import approve_all_candidates, extracted_fixture

from app.api.routes.knowledge_graph import GraphExploreIn
from app.services import knowledge_graph_query as query
from app.services.knowledge_graph_publication import (
    claim_next_job,
    complete_job,
    enqueue_publication,
)
from app.services.knowledge_graph_snapshot import build_snapshot


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def single(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class FakeTx:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        if cypher == query.READ_META:
            return FakeResult([{"revision": 2}])
        return FakeResult([])


class FakeDriver:
    def __init__(self, tx):
        self.tx = tx

    def session(self, *, database):
        assert database == "neo4j"
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute_read(self, callback):
        return callback(self.tx)


def test_cypher_is_fixed_and_receives_only_concept_id():
    tx = FakeTx()
    concept_id = uuid4()
    revision, rows = query._read_graph(
        FakeDriver(tx), concept_id, ("HAS_RED_FLAG",), "neo4j"
    )
    assert revision == 2 and rows == []
    assert tx.calls[1][0] == query.READ_NEIGHBORS
    assert tx.calls[1][1] == {
        "concept_id": str(concept_id),
        "predicates": ["HAS_RED_FLAG"],
        "limit": query.MAX_GRAPH_CLAIMS,
    }


def test_explore_contract_rejects_cypher_and_unbounded_depth():
    with pytest.raises(ValidationError):
        GraphExploreIn.model_validate({"conceptId": str(uuid4()), "cypher": "MATCH (n)"})
    with pytest.raises(ValidationError):
        GraphExploreIn.model_validate({"conceptId": str(uuid4()), "depth": 3})


async def test_question_topic_match_uses_published_names_and_aliases(
    profile_context, monkeypatch
):
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    await enqueue_publication(db, actor="图谱测试")
    monkeypatch.setattr(query.get_settings(), "neo4j_read_enabled", True)

    exact = await query.find_public_question_concepts(db, "肺癌有哪些常见表现？")
    alias = await query.find_public_question_concepts(db, "支气管肺癌的科普资料？")
    unrelated = await query.find_public_question_concepts(db, "今天天气怎样？")

    assert [item.canonical_name for item in exact] == ["肺癌"]
    assert [item.canonical_name for item in alias] == ["肺癌"]
    assert unrelated == []


async def test_unknown_predicate_rejected_before_database(profile_context):
    _, db, _ = profile_context
    with pytest.raises(ValueError, match="关系类型"):
        await query.explore_public_graph(db, uuid4(), predicates=("MATCH (n) RETURN n",))


async def test_revision_and_live_evidence_gate(profile_context, monkeypatch):
    _, db, _ = profile_context
    document, _ = await extracted_fixture(db)
    await approve_all_candidates(db)
    publication = await enqueue_publication(db, actor="医学测试员")
    job = await claim_next_job(db, owner="test")
    assert job is not None
    await complete_job(db, job.job_id, owner="test")
    snapshot = await build_snapshot(db, revision=publication.revision)
    row = snapshot.claims[0]
    concept_id = UUID(row["subject_id"])

    async def read_graph(_concept_id, _predicates):
        return publication.revision, [
            {
                "claim_id": row["id"],
                "subject_id": row["subject_id"],
                "object_id": row["object_id"],
                "predicate": row["predicate"],
            }
        ]

    monkeypatch.setattr(query, "_read_neo4j", read_graph)
    result = await query.explore_public_graph(db, concept_id)
    assert result.available and len(result.relations) == 1
    assert result.relations[0].evidence[0]["chunkId"]
    assert "content" not in result.relations[0].evidence[0]

    document.review_status = "superseded"
    await db.flush()
    revoked = await query.explore_public_graph(db, concept_id)
    assert revoked.available and revoked.relations == ()

    async def stale_graph(_concept_id, _predicates):
        return publication.revision - 1, []

    monkeypatch.setattr(query, "_read_neo4j", stale_graph)
    stale = await query.explore_public_graph(db, concept_id)
    assert not stale.available and stale.relations == ()


async def test_graph_failure_falls_back_to_unavailable(profile_context, monkeypatch):
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    await enqueue_publication(db, actor="医学测试员")
    job = await claim_next_job(db, owner="test")
    assert job is not None
    await complete_job(db, job.job_id, owner="test")
    snapshot = await build_snapshot(db, revision=job.target_revision)

    async def failed(_concept_id, _predicates):
        raise OSError("connection refused")

    monkeypatch.setattr(query, "_read_neo4j", failed)
    result = await query.explore_public_graph(db, UUID(snapshot.claims[0]["subject_id"]))
    assert not result.available and result.relations == ()
