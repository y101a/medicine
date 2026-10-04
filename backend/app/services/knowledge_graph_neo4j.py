"""固定 Cypher 模板写入全量快照；从不接受模型生成的查询。"""

from app.services.knowledge_graph_snapshot import GraphSnapshot

SCHEMA_QUERIES = (
    "CREATE CONSTRAINT public_concept_id IF NOT EXISTS "
    "FOR (n:PublicConcept) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT public_claim_id IF NOT EXISTS FOR (n:PublicClaim) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT public_evidence_id IF NOT EXISTS "
    "FOR (n:PublicEvidence) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT public_graph_meta_id IF NOT EXISTS "
    "FOR (n:PublicGraphMeta) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX public_concept_name IF NOT EXISTS FOR (n:PublicConcept) ON (n.normalized_name)",
)

DELETE_SNAPSHOT = "MATCH (n:PublicMedicalGraph) DETACH DELETE n"
WRITE_CONCEPTS = """
UNWIND $rows AS row
CREATE (n:PublicConcept:PublicMedicalGraph {
  id: row.id, concept_type: row.concept_type, canonical_name: row.canonical_name,
  normalized_name: row.normalized_name, version: row.version, aliases: row.aliases
})
"""
WRITE_CLAIMS = """
UNWIND $rows AS row
MATCH (subject:PublicConcept {id: row.subject_id})
MATCH (object:PublicConcept {id: row.object_id})
CREATE (c:PublicClaim:PublicMedicalGraph {id: row.id, predicate: row.predicate})
CREATE (subject)-[:CLAIM_SUBJECT]->(c)-[:CLAIM_OBJECT]->(object)
"""
WRITE_EVIDENCE = """
UNWIND $rows AS row
MATCH (c:PublicClaim {id: row.claim_id})
CREATE (e:PublicEvidence:PublicMedicalGraph {
  id: row.id, document_id: row.document_id, chunk_id: row.chunk_id
})
CREATE (c)-[:SUPPORTED_BY]->(e)
"""
WRITE_META = """
CREATE (:PublicGraphMeta:PublicMedicalGraph {id: 'public-medical', revision: $revision,
  concept_count: $concept_count, claim_count: $claim_count, evidence_count: $evidence_count})
"""


class Neo4jProjectionError(RuntimeError):
    pass


def _replace_snapshot(tx, snapshot: GraphSnapshot) -> None:
    current = tx.run(
        "MATCH (m:PublicGraphMeta {id: $id}) RETURN m.revision AS revision",
        id="public-medical",
    ).single()
    if current is not None and current["revision"] >= snapshot.revision:
        if current["revision"] == snapshot.revision:
            return
        raise Neo4jProjectionError("图谱已有更新 revision，拒绝旧任务覆盖")
    tx.run(DELETE_SNAPSHOT).consume()
    if snapshot.concepts:
        tx.run(WRITE_CONCEPTS, rows=snapshot.concepts).consume()
    if snapshot.claims:
        tx.run(WRITE_CLAIMS, rows=snapshot.claims).consume()
    if snapshot.evidence:
        tx.run(WRITE_EVIDENCE, rows=snapshot.evidence).consume()
    tx.run(
        WRITE_META,
        revision=snapshot.revision,
        concept_count=len(snapshot.concepts),
        claim_count=len(snapshot.claims),
        evidence_count=len(snapshot.evidence),
    ).consume()


def project_snapshot(driver, snapshot: GraphSnapshot, *, database: str = "neo4j") -> None:
    """单事务替换：失败则旧快照完整保留。driver 可由测试替身注入。"""

    with driver.session(database=database) as session:
        for query in SCHEMA_QUERIES:
            session.run(query).consume()
        session.execute_write(_replace_snapshot, snapshot)
