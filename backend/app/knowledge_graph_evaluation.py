"""Isolated, unreviewed PostgreSQL + Neo4j retrieval comparison.

Only runs against the disposable graph-eval services. This is an engineering
benchmark, not a medical review or an answer-correctness benchmark.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from neo4j import GraphDatabase

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.knowledge_graph_candidate_check import build_evaluation_manifest
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.retrieval import search_knowledge
from app.services.knowledge_graph_neo4j import project_snapshot
from app.services.knowledge_graph_snapshot import GraphSnapshot
from app.services.knowledge_graph_vocabulary import normalize_concept_name

DOCS = Path(__file__).resolve().parents[1] / "docs"
PACKAGE = DOCS / "knowledge_graph_evaluation_batch1.json"
CASE_SETS = {
    "batch1": DOCS / "knowledge_graph_evaluation_batch1_cases.json",
    "batch2": DOCS / "knowledge_graph_evaluation_batch2_cases.json",
}
NEO4J_URI = "bolt://127.0.0.1:57687"
NEO4J_PASSWORD = "graph-eval-local-only"
READ_RELATIONS = """
MATCH (s:PublicConcept {id: $subject_id})-[:CLAIM_SUBJECT]->
      (c:PublicClaim)-[:CLAIM_OBJECT]->(o:PublicConcept)
MATCH (c)-[:SUPPORTED_BY]->(e:PublicEvidence)
RETURN c.id AS claim_id, o.canonical_name AS object_name, e.chunk_id AS chunk_id
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _choose_topic(question: str, concepts: list[dict]) -> str | None:
    normalized = normalize_concept_name(question)
    scored = [
        (
            max(
                (len(term) for raw in [row["canonical_name"], *row["aliases"]]
                 if (term := normalize_concept_name(raw)) in normalized and len(term) >= 2),
                default=0,
            ),
            row["id"],
        )
        for row in concepts if row["concept_type"] == "topic"
    ]
    best = max((length for length, _ in scored), default=0)
    winners = [id_ for length, id_ in scored if length == best and best > 0]
    return winners[0] if len(winners) == 1 else None


async def _seed_prototype(db, package: dict) -> GraphSnapshot:
    """Create unreviewed sources/chunks in a transaction that caller rolls back."""

    now = datetime.now(UTC)
    concept_rows: dict[tuple[str, str], dict] = {}
    claims: list[dict] = []
    evidence: list[dict] = []
    aliases = {
        "儿童发热": ["孩子发烧", "小孩发热"],
        "炎症": ["发炎"],
        "抗菌药物": ["抗菌药"],
        "科学运动": ["健身", "运动"],
    }
    for topic in package["topics"]:
        key = topic["topic_key"]
        source = KnowledgeSource(
            source_key=f"graph-eval-{key}", priority=1,
            organization=topic["source"]["publisher"],
            channel_name="图谱隔离评测（暂未经专业医学审核）",
            authority_level="evaluation_only", entry_url=topic["source"]["url"],
            ingestion_status="prototype", automated_collection=False,
            source_metadata={"evaluation_only": True, "medical_reviewed": False},
        )
        db.add(source)
        await db.flush()
        content = "\n".join(topic["excerpts"])
        document = KnowledgeDocument(
            source_id=source.id, canonical_url=topic["source"]["url"],
            title=topic["title"], content_type="web_page", language="zh-CN",
            published_at=now, retrieved_at=now, review_status="prototype",
            content_hash=_hash(content), content_text=content,
            document_metadata={"evaluation_only": True, "medical_reviewed": False},
        )
        db.add(document)
        await db.flush()
        chunks = []
        for index, excerpt in enumerate(topic["excerpts"]):
            chunk = KnowledgeChunk(
                document_id=document.id, chunk_index=index,
                section_title=topic["title"], content=excerpt,
                content_hash=_hash(excerpt),
                chunk_metadata={"evaluation_only": True},
            )
            db.add(chunk)
            chunks.append(chunk)
        await db.flush()
        for concept in topic["concepts"]:
            identity = (concept["concept_type"], concept["canonical_name"])
            if identity not in concept_rows:
                concept_rows[identity] = {
                    "id": str(uuid4()), "concept_type": concept["concept_type"],
                    "canonical_name": concept["canonical_name"],
                    "normalized_name": normalize_concept_name(concept["canonical_name"]),
                    "version": 1,
                    "aliases": aliases.get(concept["canonical_name"], []),
                }
        for triple in topic["candidate_triples"]:
            subject = concept_rows[("topic", triple["subject"])]
            object_ = next(
                row for (kind, name), row in concept_rows.items()
                if name == triple["object"] and kind != "topic"
            ) if triple["predicate"] != "RELATED_TOPIC" else concept_rows[
                ("topic", triple["object"])
            ]
            chunk = next(
                row for row in chunks if triple["evidence_excerpt"] in row.content
            )
            claim_id = str(uuid4())
            claims.append({
                "id": claim_id, "subject_id": subject["id"],
                "predicate": triple["predicate"], "object_id": object_["id"],
            })
            evidence.append({
                "id": str(uuid4()), "claim_id": claim_id,
                "document_id": str(document.id), "chunk_id": str(chunk.id),
            })
    return GraphSnapshot(1, list(concept_rows.values()), claims, evidence)


async def run(case_set: str = "batch1") -> dict:
    settings = get_settings()
    if not (
        settings.app_environment == "development"
        and settings.postgres_db == "medical_assistant_graph_eval"
        and settings.postgres_port == 55432
    ):
        raise RuntimeError("只允许连接独立的 medical_assistant_graph_eval:55432")
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    manifest = build_evaluation_manifest(package)
    if not manifest["ok"] or manifest["eligible_for_publication"]:
        raise RuntimeError("评测材料不符合 pending / 不可发布门槛")
    cases = json.loads(CASE_SETS[case_set].read_text(encoding="utf-8"))["cases"]
    results = []
    async with SessionLocal() as db:
        try:
            snapshot = await _seed_prototype(db, package)
            with GraphDatabase.driver(
                NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD)
            ) as driver:
                driver.verify_connectivity()
                with driver.session(database="neo4j") as session:
                    old = session.run(
                        "MATCH (m:PublicGraphMeta {id: $id}) RETURN m.revision AS revision",
                        id="public-medical",
                    ).single()
                if old is not None:
                    raise RuntimeError("隔离 Neo4j 并非空图；拒绝覆盖已有数据")
                project_snapshot(driver, snapshot)
                for case in cases:
                    start = perf_counter()
                    rag = await search_knowledge(
                        db, case["query"], top_k=4, mode="keyword", scope="auto"
                    )
                    rag_ms = round((perf_counter() - start) * 1000, 1)
                    cited_chunks = {str(item.chunk_id) for item in rag.items}
                    source_hit = any(
                        item.source_key == f"graph-eval-{case['expected_source']}"
                        for item in rag.items
                    ) if case["expected_source"] else False
                    graph_start = perf_counter()
                    selected = _choose_topic(case["query"], snapshot.concepts)
                    matched = set()
                    if selected:
                        with driver.session(database="neo4j") as session:
                            for row in session.run(READ_RELATIONS, subject_id=selected):
                                if row["chunk_id"] in cited_chunks:
                                    matched.add(row["object_name"])
                    graph_ms = round((perf_counter() - graph_start) * 1000, 1)
                    expected = set(case["expected_objects"])
                    results.append({
                        "id": case["id"], "split": case["split"],
                        "case_type": case["case_type"],
                        "rag_source_hit": source_hit,
                        "graph_triggered": selected is not None,
                        "graph_objects": sorted(matched),
                        "expected_objects": sorted(expected),
                        "graph_expected_hit": bool(expected and expected & matched),
                        "graph_unexpected": sorted(matched - expected),
                        "rag_ms": rag_ms, "graph_extra_ms": graph_ms,
                    })
        finally:
            await db.rollback()
    supported = [row for row in results if row["case_type"] == "supported"]
    negatives = [row for row in results if row["case_type"] != "supported"]
    return {
        "medical_review_label": "暂未经专业医学审核",
        "case_set": case_set,
        "mode": "real_postgresql_keyword_rag_vs_evaluation_neo4j",
        "answer_quality_scored": False,
        "cases": len(results),
        "rag_source_hits": sum(row["rag_source_hit"] for row in supported),
        "supported_cases": len(supported),
        "graph_expected_hits": sum(row["graph_expected_hit"] for row in supported),
        "negative_graph_returns": sum(bool(row["graph_objects"]) for row in negatives),
        "negative_cases": len(negatives),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated-eval", action="store_true", required=True)
    parser.add_argument("--case-set", choices=tuple(CASE_SETS), default="batch1")
    args = parser.parse_args()
    if not args.isolated_eval:
        parser.error("必须显式确认隔离评测")
    print(json.dumps(asyncio.run(run(args.case_set)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
