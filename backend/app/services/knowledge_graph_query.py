"""Read-only public graph lookup. Neo4j is never trusted as the source of facts."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import KnowledgeDocument
from app.models.knowledge_graph import (
    ConceptType,
    GraphClaim,
    GraphClaimPredicate,
    GraphClaimStatus,
    GraphConcept,
    GraphConceptAlias,
    GraphConceptStatus,
    GraphReviewDecision,
)
from app.services.knowledge_graph_publication import publication_status
from app.services.knowledge_graph_review import _load_evidence
from app.services.knowledge_graph_vocabulary import (
    KnowledgeGraphVocabularyError,
    normalize_concept_name,
    validate_triple,
)

MAX_GRAPH_CLAIMS = 30
READ_META = (
    "MATCH (m:PublicGraphMeta {id: $id}) RETURN m.revision AS revision"
)
READ_NEIGHBORS = """
MATCH (subject:PublicConcept {id: $concept_id})-[:CLAIM_SUBJECT]->
      (claim:PublicClaim)-[:CLAIM_OBJECT]->(object:PublicConcept)
WHERE claim.predicate IN $predicates
RETURN claim.id AS claim_id, subject.id AS subject_id, object.id AS object_id,
       claim.predicate AS predicate
LIMIT $limit
"""


@dataclass(frozen=True, slots=True)
class PublicGraphRelation:
    claim_id: UUID
    subject_id: UUID
    subject_name: str
    subject_type: str
    object_id: UUID
    object_name: str
    object_type: str
    predicate: str
    evidence: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class PublicGraphResult:
    available: bool
    revision: int | None
    relations: tuple[PublicGraphRelation, ...]


async def find_public_concepts(db: AsyncSession, query: str) -> list[GraphConcept]:
    """Only concepts participating in published claims can be suggested."""

    if not get_settings().neo4j_read_enabled:
        return []
    if not 2 <= len(query.strip()) <= 50:
        return []
    normalized = normalize_concept_name(query)
    if not 2 <= len(normalized) <= 50:
        return []
    ids = select(GraphClaim.subject_concept_id).where(
        GraphClaim.status == GraphClaimStatus.PUBLISHED,
        GraphClaim.review_decision == GraphReviewDecision.APPROVED,
    )
    aliases = select(GraphConceptAlias.concept_id).where(
        GraphConceptAlias.normalized_text == normalized,
        GraphConceptAlias.status == GraphConceptStatus.ACTIVE,
    )
    rows = await db.scalars(
        select(GraphConcept)
        .where(
            GraphConcept.status == GraphConceptStatus.ACTIVE,
            GraphConcept.id.in_(ids),
            or_(GraphConcept.normalized_name == normalized, GraphConcept.id.in_(aliases)),
        )
        .order_by(GraphConcept.canonical_name)
        .limit(5)
    )
    return list(rows.all())


async def find_public_question_concepts(db: AsyncSession, question: str) -> list[GraphConcept]:
    """Match an explicit published topic name/alias locally; fail closed on ties.

    This is separate from the web-search term extractor: ordinary graph topics
    such as 儿童发热 need not be unknown disease names. Nothing is sent to Neo4j
    except the selected concept UUID.
    """

    if not get_settings().neo4j_read_enabled or not 2 <= len(question.strip()) <= 2000:
        return []
    try:
        normalized = normalize_concept_name(question)
    except KnowledgeGraphVocabularyError:
        return []
    ids = select(GraphClaim.subject_concept_id).where(
        GraphClaim.status == GraphClaimStatus.PUBLISHED,
        GraphClaim.review_decision == GraphReviewDecision.APPROVED,
    )
    concepts = list((await db.scalars(
        select(GraphConcept).where(
            GraphConcept.status == GraphConceptStatus.ACTIVE,
            GraphConcept.concept_type == ConceptType.TOPIC,
            GraphConcept.id.in_(ids),
        ).limit(2001)
    )).all())
    if len(concepts) > 2000 or not concepts:
        return []
    concept_ids = [concept.id for concept in concepts]
    aliases = (await db.scalars(
        select(GraphConceptAlias).where(
            GraphConceptAlias.concept_id.in_(concept_ids),
            GraphConceptAlias.status == GraphConceptStatus.ACTIVE,
        )
    )).all()
    terms: dict[UUID, set[str]] = {
        concept.id: {concept.normalized_name} for concept in concepts
    }
    for alias in aliases:
        terms[alias.concept_id].add(alias.normalized_text)
    ranked = [
        (max((len(term) for term in terms[concept.id]
              if len(term) >= 2 and term in normalized), default=0), concept)
        for concept in concepts
    ]
    best = max((length for length, _ in ranked), default=0)
    return [concept for length, concept in ranked if length == best] if best else []


def _read_graph(
    driver, concept_id: UUID, predicates: tuple[str, ...], database: str, query_wrapper=None
):
    """The only Cypher sent to Neo4j is fixed here; IDs and predicates are parameters."""

    def read(tx):
        meta_query = query_wrapper(READ_META) if query_wrapper else READ_META
        neighbor_query = query_wrapper(READ_NEIGHBORS) if query_wrapper else READ_NEIGHBORS
        meta = tx.run(meta_query, id="public-medical").single()
        if meta is None:
            return None, []
        rows = tx.run(
            neighbor_query,
            concept_id=str(concept_id),
            predicates=list(predicates),
            limit=MAX_GRAPH_CLAIMS,
        )
        return meta["revision"], [dict(row) for row in rows]

    with driver.session(database=database) as session:
        return session.execute_read(read)


async def _read_neo4j(concept_id: UUID, predicates: tuple[str, ...]):
    settings = get_settings()
    if not (
        settings.neo4j_read_enabled
        and settings.neo4j_uri
        and settings.neo4j_read_username
        and settings.neo4j_read_password
    ):
        return None, []

    def run():
        from neo4j import GraphDatabase, Query

        with GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(
                settings.neo4j_read_username,
                settings.neo4j_read_password.get_secret_value(),
            ),
            connection_timeout=2,
            max_connection_pool_size=2,
        ) as driver:
            return _read_graph(
                driver,
                concept_id,
                predicates,
                settings.neo4j_database,
                query_wrapper=lambda text: Query(text, timeout=2),
            )

    return await asyncio.wait_for(asyncio.to_thread(run), timeout=3)


async def explore_public_graph(
    db: AsyncSession,
    concept_id: UUID,
    *,
    predicates: tuple[str, ...] | None = None,
) -> PublicGraphResult:
    """Fail closed on missing revision, invalid evidence, or Neo4j failure."""

    allowed = {item.value for item in GraphClaimPredicate}
    selected = tuple(sorted(allowed if predicates is None else set(predicates)))
    if not selected or not set(selected) <= allowed:
        raise ValueError("不支持的图谱关系类型")
    concept = await db.get(GraphConcept, concept_id)
    if concept is None or concept.status != GraphConceptStatus.ACTIVE:
        return PublicGraphResult(False, None, ())
    status = await publication_status(db)
    if (
        status.expected_revision < 1
        or status.last_published_revision != status.expected_revision
    ):
        return PublicGraphResult(False, None, ())
    try:
        graph_revision, rows = await _read_neo4j(concept_id, selected)
    except Exception:
        return PublicGraphResult(False, None, ())
    if graph_revision != status.expected_revision:
        return PublicGraphResult(False, None, ())
    parsed = []
    try:
        for row in rows[:MAX_GRAPH_CLAIMS]:
            claim_id = UUID(row["claim_id"])
            subject_id = UUID(row["subject_id"])
            object_id = UUID(row["object_id"])
            if subject_id != concept_id or row["predicate"] not in selected:
                return PublicGraphResult(False, None, ())
            parsed.append((claim_id, subject_id, object_id, row["predicate"]))
    except (KeyError, TypeError, ValueError):
        return PublicGraphResult(False, None, ())
    claim_ids = [row[0] for row in parsed]
    claim_rows = await db.scalars(select(GraphClaim).where(GraphClaim.id.in_(claim_ids)))
    claims = {claim.id: claim for claim in claim_rows.all()}
    concept_ids = {item for row in parsed for item in (row[1], row[2])}
    concept_rows = await db.scalars(select(GraphConcept).where(GraphConcept.id.in_(concept_ids)))
    concepts = {item.id: item for item in concept_rows.all()}
    evidence = await _load_evidence(db, claim_ids)
    document_ids = {
        item.document_id for items in evidence.values() for item in items if item.valid
    }
    documents = {
        item.id: item
        for item in (
            await db.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids))
            )
        ).all()
    }
    relations = []
    for claim_id, subject_id, object_id, predicate in parsed:
        claim = claims.get(claim_id)
        subject = concepts.get(subject_id)
        object_ = concepts.get(object_id)
        valid_evidence = [item for item in evidence.get(claim_id, []) if item.valid]
        if not (
            claim
            and subject
            and object_
            and claim.status == GraphClaimStatus.PUBLISHED
            and claim.review_decision == GraphReviewDecision.APPROVED
            and claim.subject_concept_id == subject_id
            and claim.object_concept_id == object_id
            and claim.predicate == predicate
            and subject.status == GraphConceptStatus.ACTIVE
            and object_.status == GraphConceptStatus.ACTIVE
            and valid_evidence
        ):
            continue
        try:
            validate_triple(subject.concept_type, predicate, object_.concept_type)
        except KnowledgeGraphVocabularyError:
            continue
        relations.append(
            PublicGraphRelation(
                claim_id=claim_id,
                subject_id=subject_id,
                subject_name=subject.canonical_name,
                subject_type=subject.concept_type,
                object_id=object_id,
                object_name=object_.canonical_name,
                object_type=object_.concept_type,
                predicate=predicate,
                evidence=tuple(
                    {
                        "documentId": str(item.document_id),
                        "chunkId": str(item.chunk_id),
                        "title": item.document_title,
                        "section": item.section_title or "",
                        "url": documents[item.document_id].canonical_url,
                    }
                    for item in valid_evidence[:3]
                ),
            )
        )
    return PublicGraphResult(True, int(graph_revision), tuple(relations))
