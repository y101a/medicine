"""从 PostgreSQL 当前有效事实构造可重建的公共医学图快照。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import (
    GraphClaim,
    GraphClaimStatus,
    GraphConceptAlias,
    GraphConceptStatus,
    GraphReviewDecision,
)
from app.services.knowledge_graph_review import _blocking_reason, _load_concepts, _load_evidence


class GraphSnapshotError(ValueError):
    """当前已发布事实不符合投影硬门槛。"""


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    revision: int
    concepts: list[dict[str, str | int]]
    claims: list[dict[str, str]]
    evidence: list[dict[str, str | int | None]]


async def build_snapshot(db: AsyncSession, *, revision: int) -> GraphSnapshot:
    if revision < 1:
        raise GraphSnapshotError("revision 必须为正")
    claim_query = select(GraphClaim).where(GraphClaim.status == GraphClaimStatus.PUBLISHED)
    claims = list((await db.scalars(claim_query)).all())
    concepts_by_id = await _load_concepts(db)
    evidence_by_claim = await _load_evidence(db, [claim.id for claim in claims])
    for claim in claims:
        if claim.review_decision != GraphReviewDecision.APPROVED:
            raise GraphSnapshotError(f"已发布关系未审核：{claim.id}")
        reason = _blocking_reason(claim, concepts_by_id, evidence_by_claim.get(claim.id, []))
        if reason:
            raise GraphSnapshotError(f"已发布关系证据失效：{claim.id}：{reason}")

    used_ids = {
        id_
        for claim in claims
        for id_ in (claim.subject_concept_id, claim.object_concept_id)
    }
    concepts = [
        {
            "id": str(concept.id),
            "concept_type": concept.concept_type,
            "canonical_name": concept.canonical_name,
            "normalized_name": concept.normalized_name,
            "version": concept.version,
        }
        for concept in concepts_by_id.values()
        if concept.id in used_ids and concept.status == GraphConceptStatus.ACTIVE
    ]
    alias_query = select(GraphConceptAlias).where(
        GraphConceptAlias.status == GraphConceptStatus.ACTIVE
    )
    aliases = list((await db.scalars(alias_query)).all())
    alias_map: dict[str, list[str]] = {}
    for alias in aliases:
        if alias.concept_id in used_ids:
            alias_map.setdefault(str(alias.concept_id), []).append(alias.text)
    for concept in concepts:
        concept["aliases"] = sorted(alias_map.get(str(concept["id"]), []))

    claim_rows = [
        {
            "id": str(claim.id),
            "subject_id": str(claim.subject_concept_id),
            "predicate": claim.predicate,
            "object_id": str(claim.object_concept_id),
        }
        for claim in claims
    ]
    evidence_rows = [
        {
            "id": str(item.evidence_id),
            "claim_id": str(claim.id),
            "document_id": str(item.document_id),
            "chunk_id": str(item.chunk_id),
        }
        for claim in claims
        for item in evidence_by_claim.get(claim.id, [])
        if item.valid
    ]
    return GraphSnapshot(revision, concepts, claim_rows, evidence_rows)
