"""医学审核、状态查询与图谱校验（G1）。

这一层是「未经审核的关系绝不外泄」的执行点：发布门槛写在这里，而不是写在文档里——

- 审核通过要求**至少一条仍然有效**的证据：文档仍是 `approved`，且证据记录的
  `chunk_content_hash` 与当前知识块一致（不一致说明正文被改过，必须重新看一遍）；
- 两端概念必须仍在用，三元组两端的类型必须符合 predicate 的冻结规则；
- 发布与撤回都要留下人和时间；撤回是 `retired`，不删除行（历史引用不漂移）；
- `verify_graph` 把 plan 第 12.1 节的硬门槛变成可跑的检查，而不是靠人工记得去看。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.models.knowledge_graph import (
    GraphClaim,
    GraphClaimEvidence,
    GraphClaimStatus,
    GraphConcept,
    GraphConceptStatus,
    GraphPublicationJob,
    GraphPublicationStatus,
    GraphReviewDecision,
)
from app.services.knowledge_graph_vocabulary import (
    KnowledgeGraphVocabularyError,
    describe_triple,
    validate_triple,
)

APPROVED_DOCUMENT_STATUS = "approved"
_EXCERPT_LIMIT = 200


class KnowledgeGraphReviewError(ValueError):
    """审核动作不合法：状态不允许、证据无效、概念已停用等。"""


@dataclass(slots=True)
class EvidenceView:
    evidence_id: UUID
    chunk_id: UUID
    document_id: UUID
    document_title: str
    document_status: str
    section_title: str | None
    excerpt: str
    hash_matches: bool
    valid: bool
    invalid_reason: str | None


@dataclass(slots=True)
class ReviewQueueItem:
    claim_id: UUID
    description: str
    predicate: str
    subject_name: str
    subject_type: str
    object_name: str
    object_type: str
    status: str
    review_decision: str
    extraction_source: str
    extraction_version: str
    evidence: list[EvidenceView]
    publishable: bool
    blocking_reason: str | None


@dataclass(slots=True)
class ClaimReviewResult:
    claim_id: UUID
    status: str
    review_decision: str
    reviewer: str
    valid_evidence_count: int


@dataclass(slots=True)
class GraphStatus:
    concepts_by_type: dict[str, int]
    concepts_by_status: dict[str, int]
    claims_by_status: dict[str, int]
    claims_by_decision: dict[str, int]
    live_claims: int
    stale_live_claims: int
    evidence_rows: int
    expected_revision: int
    last_published_revision: int | None
    last_job_status: str | None


@dataclass(slots=True)
class VerificationIssue:
    code: str
    message: str
    claim_ids: list[UUID] = field(default_factory=list)


@dataclass(slots=True)
class VerificationReport:
    published_claims: int
    evidence_rows: int
    expected_revision: int
    last_published_revision: int | None
    revision_in_sync: bool
    issues: list[VerificationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


async def _load_claims(db: AsyncSession) -> list[GraphClaim]:
    return list((await db.scalars(select(GraphClaim).order_by(GraphClaim.created_at))).all())


async def _load_concepts(db: AsyncSession) -> dict[UUID, GraphConcept]:
    concepts = list((await db.scalars(select(GraphConcept))).all())
    return {concept.id: concept for concept in concepts}


async def _load_evidence(
    db: AsyncSession, claim_ids: list[UUID]
) -> dict[UUID, list[EvidenceView]]:
    """一次查完这些 claim 的全部证据，并就地判定「是否仍然有效」。"""

    grouped: dict[UUID, list[EvidenceView]] = {claim_id: [] for claim_id in claim_ids}
    if not claim_ids:
        return grouped
    rows = (
        await db.execute(
            select(GraphClaimEvidence, KnowledgeChunk, KnowledgeDocument, KnowledgeSource)
            .join(KnowledgeChunk, KnowledgeChunk.id == GraphClaimEvidence.chunk_id)
            .join(KnowledgeDocument, KnowledgeDocument.id == GraphClaimEvidence.document_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(GraphClaimEvidence.claim_id.in_(claim_ids))
            .order_by(GraphClaimEvidence.created_at)
        )
    ).all()
    for evidence, chunk, document, source in rows:
        hash_matches = chunk.content_hash == evidence.chunk_content_hash
        reasons: list[str] = []
        if document.review_status != APPROVED_DOCUMENT_STATUS:
            reasons.append(f"来源文档状态是 {document.review_status}")
        if source.ingestion_status != APPROVED_DOCUMENT_STATUS:
            reasons.append(f"来源状态是 {source.ingestion_status}")
        if not hash_matches:
            reasons.append("知识块正文已变更，需要重新审核")
        grouped[evidence.claim_id].append(
            EvidenceView(
                evidence_id=evidence.id,
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                document_status=document.review_status,
                section_title=chunk.section_title,
                excerpt=_excerpt(chunk.content, evidence.span_start, evidence.span_end),
                hash_matches=hash_matches,
                valid=not reasons,
                invalid_reason="；".join(reasons) if reasons else None,
            )
        )
    return grouped


def _excerpt(content: str, span_start: int | None, span_end: int | None) -> str:
    if span_start is not None and span_end is not None and span_end <= len(content):
        text = content[span_start:span_end]
    else:
        text = content
    text = " ".join(text.split())
    return text if len(text) <= _EXCERPT_LIMIT else f"{text[:_EXCERPT_LIMIT]}…"


def _blocking_reason(
    claim: GraphClaim,
    concepts: dict[UUID, GraphConcept],
    evidence: list[EvidenceView],
) -> str | None:
    """不能发布的第一个原因（给审核队列直接显示，而不是让用户去猜）。"""

    subject = concepts.get(claim.subject_concept_id)
    object_ = concepts.get(claim.object_concept_id)
    if subject is None or object_ is None:
        return "关系指向的概念已不存在"
    if subject.status != GraphConceptStatus.ACTIVE:
        return f"主语概念「{subject.canonical_name}」已停用"
    if object_.status != GraphConceptStatus.ACTIVE:
        return f"宾语概念「{object_.canonical_name}」已停用"
    try:
        validate_triple(subject.concept_type, claim.predicate, object_.concept_type)
    except KnowledgeGraphVocabularyError as exc:
        return str(exc)
    if not evidence:
        return "没有任何证据，不能发布"
    if not any(item.valid for item in evidence):
        return evidence[0].invalid_reason or "证据已失效"
    return None


def _require_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise KnowledgeGraphReviewError(f"{label}不能为空")
    if len(cleaned) > 200:
        raise KnowledgeGraphReviewError(f"{label}不能超过 200 字")
    return cleaned


async def list_review_queue(
    db: AsyncSession,
    *,
    limit: int = 20,
    decision: GraphReviewDecision | str = GraphReviewDecision.PENDING,
) -> list[ReviewQueueItem]:
    """待审核队列：连通俗中文、证据原文和「不能发布的原因」一起给出来。"""

    resolved = GraphReviewDecision(decision)
    claims = [
        claim
        for claim in await _load_claims(db)
        if claim.review_decision == resolved and claim.status != GraphClaimStatus.RETIRED
    ][:limit]
    concepts = await _load_concepts(db)
    evidence_by_claim = await _load_evidence(db, [claim.id for claim in claims])
    items: list[ReviewQueueItem] = []
    for claim in claims:
        subject = concepts.get(claim.subject_concept_id)
        object_ = concepts.get(claim.object_concept_id)
        evidence = evidence_by_claim.get(claim.id, [])
        blocking = _blocking_reason(claim, concepts, evidence)
        items.append(
            ReviewQueueItem(
                claim_id=claim.id,
                description=describe_triple(
                    subject.canonical_name if subject else "（缺失）",
                    claim.predicate,
                    object_.canonical_name if object_ else "（缺失）",
                ),
                predicate=claim.predicate,
                subject_name=subject.canonical_name if subject else "（缺失）",
                subject_type=subject.concept_type if subject else "unknown",
                object_name=object_.canonical_name if object_ else "（缺失）",
                object_type=object_.concept_type if object_ else "unknown",
                status=claim.status,
                review_decision=claim.review_decision,
                extraction_source=claim.extraction_source,
                extraction_version=claim.extraction_version,
                evidence=evidence,
                publishable=blocking is None,
                blocking_reason=blocking,
            )
        )
    return items


async def approve_claim(
    db: AsyncSession,
    claim_id: UUID,
    *,
    reviewer: str,
    note: str | None = None,
) -> ClaimReviewResult:
    """医学审核通过。没有有效证据、概念停用或类型不符时一律不通过。"""

    actor = _require_text(reviewer, "审核人")
    claim = await _get_claim(db, claim_id)
    if claim.status in (GraphClaimStatus.PUBLISHED, GraphClaimStatus.RETIRED):
        raise KnowledgeGraphReviewError(
            "已发布或已撤回的关系不能重复审核；如需下线请用 retire-claim"
        )
    concepts = await _load_concepts(db)
    evidence = (await _load_evidence(db, [claim.id])).get(claim.id, [])
    blocking = _blocking_reason(claim, concepts, evidence)
    if blocking is not None:
        raise KnowledgeGraphReviewError(f"不能通过审核：{blocking}")
    claim.review_decision = GraphReviewDecision.APPROVED
    claim.medical_reviewed_by = actor
    claim.medical_reviewed_at = datetime.now(UTC)
    claim.review_note = (note or "").strip() or None
    claim.status = GraphClaimStatus.REVIEWED
    await db.flush()
    return ClaimReviewResult(
        claim_id=claim.id,
        status=claim.status,
        review_decision=claim.review_decision,
        reviewer=actor,
        valid_evidence_count=sum(1 for item in evidence if item.valid),
    )


async def reject_claim(
    db: AsyncSession, claim_id: UUID, *, reviewer: str, note: str
) -> ClaimReviewResult:
    """拒绝：必须写原因，且不进入 reviewed。"""

    return await _decide(db, claim_id, reviewer=reviewer, note=note, decision="rejected")


async def return_claim(
    db: AsyncSession, claim_id: UUID, *, reviewer: str, note: str
) -> ClaimReviewResult:
    """退回修改：必须写原因，候选保留待改。"""

    return await _decide(db, claim_id, reviewer=reviewer, note=note, decision="returned")


async def _decide(
    db: AsyncSession,
    claim_id: UUID,
    *,
    reviewer: str,
    note: str,
    decision: str,
) -> ClaimReviewResult:
    actor = _require_text(reviewer, "审核人")
    reason = _require_text(note, "原因")
    claim = await _get_claim(db, claim_id)
    if claim.status in (GraphClaimStatus.PUBLISHED, GraphClaimStatus.RETIRED):
        raise KnowledgeGraphReviewError("已发布或已撤回的关系不能改判；如需下线请用 retire-claim")
    claim.review_decision = GraphReviewDecision(decision)
    claim.medical_reviewed_by = actor
    claim.medical_reviewed_at = datetime.now(UTC)
    claim.review_note = reason
    claim.status = GraphClaimStatus.CANDIDATE
    await db.flush()
    evidence = (await _load_evidence(db, [claim.id])).get(claim.id, [])
    return ClaimReviewResult(
        claim_id=claim.id,
        status=claim.status,
        review_decision=claim.review_decision,
        reviewer=actor,
        valid_evidence_count=sum(1 for item in evidence if item.valid),
    )


async def retire_claim(
    db: AsyncSession, claim_id: UUID, *, reviewer: str, reason: str
) -> ClaimReviewResult:
    """撤回：已审核或已发布的关系下线（不删除行，历史与 revision 都留着）。"""

    actor = _require_text(reviewer, "撤回人")
    why = _require_text(reason, "撤回原因")
    claim = await _get_claim(db, claim_id)
    if claim.status == GraphClaimStatus.RETIRED:
        raise KnowledgeGraphReviewError("这条关系已经撤回过了")
    if claim.status not in (GraphClaimStatus.REVIEWED, GraphClaimStatus.PUBLISHED):
        raise KnowledgeGraphReviewError("只能撤回已审核或已发布的关系；候选请用 reject 或 return")
    was_published = claim.status == GraphClaimStatus.PUBLISHED
    claim.status = GraphClaimStatus.RETIRED
    claim.retired_at = datetime.now(UTC)
    claim.retired_by = actor
    claim.retire_reason = why
    await db.flush()
    if was_published:
        from app.services.knowledge_graph_publication import enqueue_snapshot_rebuild

        await enqueue_snapshot_rebuild(db, actor=actor)
    evidence = (await _load_evidence(db, [claim.id])).get(claim.id, [])
    return ClaimReviewResult(
        claim_id=claim.id,
        status=claim.status,
        review_decision=claim.review_decision,
        reviewer=actor,
        valid_evidence_count=sum(1 for item in evidence if item.valid),
    )


async def claims_ready_to_publish(db: AsyncSession) -> list[GraphClaim]:
    """可以进入发布 outbox 的关系：已审核 + approved + 至少一条有效证据 + 概念仍在用。"""

    claims = [
        claim
        for claim in await _load_claims(db)
        if claim.status == GraphClaimStatus.REVIEWED
        and claim.review_decision == GraphReviewDecision.APPROVED
    ]
    concepts = await _load_concepts(db)
    evidence_by_claim = await _load_evidence(db, [claim.id for claim in claims])
    return [
        claim
        for claim in claims
        if _blocking_reason(claim, concepts, evidence_by_claim.get(claim.id, [])) is None
    ]


async def retire_stale_claims(
    db: AsyncSession, *, reviewer: str, reason: str = "来源文档已失效或正文已变更"
) -> list[UUID]:
    """把「还活着但没有有效证据」的关系批量撤回（来源被 superseded/过期/改写时用）。"""

    actor = _require_text(reviewer, "撤回人")
    why = _require_text(reason, "撤回原因")
    claims = [
        claim
        for claim in await _load_claims(db)
        if claim.status in (GraphClaimStatus.REVIEWED, GraphClaimStatus.PUBLISHED)
    ]
    concepts = await _load_concepts(db)
    evidence_by_claim = await _load_evidence(db, [claim.id for claim in claims])
    retired: list[UUID] = []
    published_retired = False
    for claim in claims:
        if _blocking_reason(claim, concepts, evidence_by_claim.get(claim.id, [])) is None:
            continue
        published_retired |= claim.status == GraphClaimStatus.PUBLISHED
        claim.status = GraphClaimStatus.RETIRED
        claim.retired_at = datetime.now(UTC)
        claim.retired_by = actor
        claim.retire_reason = why
        retired.append(claim.id)
    if retired:
        await db.flush()
    if published_retired:
        from app.services.knowledge_graph_publication import enqueue_snapshot_rebuild

        await enqueue_snapshot_rebuild(db, actor=actor)
    return retired


async def bind_evidence(
    db: AsyncSession,
    claim_id: UUID,
    chunk_id: UUID,
    *,
    span_start: int | None = None,
    span_end: int | None = None,
) -> UUID:
    """人工补一条证据（同一 claim 与同一知识块只允许一条）。"""

    claim = await _get_claim(db, claim_id)
    if claim.status == GraphClaimStatus.RETIRED:
        raise KnowledgeGraphReviewError("已撤回的关系不再接收新证据")
    chunk = await db.get(KnowledgeChunk, chunk_id)
    if chunk is None:
        raise KnowledgeGraphReviewError(f"知识块不存在：{chunk_id}")
    existing = await db.scalar(
        select(GraphClaimEvidence).where(
            GraphClaimEvidence.claim_id == claim_id,
            GraphClaimEvidence.chunk_id == chunk_id,
        )
    )
    if existing is not None:
        raise KnowledgeGraphReviewError("这条证据已经绑过了")
    evidence = GraphClaimEvidence(
        claim_id=claim_id,
        chunk_id=chunk_id,
        document_id=chunk.document_id,
        chunk_content_hash=chunk.content_hash,
        span_start=span_start,
        span_end=span_end,
    )
    db.add(evidence)
    await db.flush()
    return evidence.id


async def graph_status(db: AsyncSession) -> GraphStatus:
    concepts = list((await db.scalars(select(GraphConcept))).all())
    claims = await _load_claims(db)
    evidence_rows = await db.scalar(select(func.count()).select_from(GraphClaimEvidence)) or 0
    live = [
        claim
        for claim in claims
        if claim.status in (GraphClaimStatus.REVIEWED, GraphClaimStatus.PUBLISHED)
    ]
    concepts_by_id = {concept.id: concept for concept in concepts}
    evidence_by_claim = await _load_evidence(db, [claim.id for claim in live])
    stale = sum(
        1
        for claim in live
        if _blocking_reason(claim, concepts_by_id, evidence_by_claim.get(claim.id, [])) is not None
    )
    last_job = await db.scalar(
        select(GraphPublicationJob)
        .where(GraphPublicationJob.status == GraphPublicationStatus.SUCCEEDED)
        .order_by(GraphPublicationJob.target_revision.desc())
    )
    expected_revision = (
        await db.scalar(select(func.max(GraphPublicationJob.target_revision)))
    ) or 0
    return GraphStatus(
        concepts_by_type=_count_by(concept.concept_type for concept in concepts),
        concepts_by_status=_count_by(concept.status for concept in concepts),
        claims_by_status=_count_by(claim.status for claim in claims),
        claims_by_decision=_count_by(claim.review_decision for claim in claims),
        live_claims=len(live),
        stale_live_claims=stale,
        evidence_rows=int(evidence_rows),
        expected_revision=expected_revision,
        last_published_revision=last_job.target_revision if last_job else None,
        last_job_status=last_job.status if last_job else None,
    )


async def verify_graph(db: AsyncSession) -> VerificationReport:
    """plan 第 12.1/15 节的硬门槛：这些必须是 0，否则不允许宣称图谱可用。"""

    concepts = await _load_concepts(db)
    claims = await _load_claims(db)
    evidence_by_claim = await _load_evidence(db, [claim.id for claim in claims])
    live = [
        claim
        for claim in claims
        if claim.status in (GraphClaimStatus.REVIEWED, GraphClaimStatus.PUBLISHED)
    ]
    issues: list[VerificationIssue] = []

    def collect(code: str, message: str, claim_ids: list[UUID]) -> None:
        if claim_ids:
            issues.append(
                VerificationIssue(code=code, message=message, claim_ids=claim_ids[:20])
            )

    collect(
        "PUBLISHED_WITHOUT_APPROVAL",
        "已发布但审核结论不是 approved",
        [
            claim.id
            for claim in claims
            if claim.status == GraphClaimStatus.PUBLISHED
            and claim.review_decision != GraphReviewDecision.APPROVED
        ],
    )
    collect(
        "LIVE_WITHOUT_VALID_EVIDENCE",
        "线上关系没有有效证据（文档失效或正文已变更）",
        [
            claim.id
            for claim in live
            if not any(item.valid for item in evidence_by_claim.get(claim.id, []))
        ],
    )
    collect(
        "EVIDENCE_HASH_MISMATCH",
        "证据指向的知识块正文已变更，未重新审核",
        [
            claim.id
            for claim in live
            if any(
                not item.hash_matches for item in evidence_by_claim.get(claim.id, [])
            )
        ],
    )
    collect(
        "EVIDENCE_DOCUMENT_NOT_APPROVED",
        "证据来自不再 approved 的文档",
        [
            claim.id
            for claim in live
            if any(
                item.document_status != APPROVED_DOCUMENT_STATUS
                for item in evidence_by_claim.get(claim.id, [])
            )
        ],
    )
    collect(
        "LIVE_CLAIM_USES_RETIRED_CONCEPT",
        "线上关系引用了已停用的概念",
        [
            claim.id
            for claim in live
            if _concept_not_active(claim, concepts)
        ],
    )
    collect(
        "APPROVED_WITHOUT_REVIEWER",
        "审核通过但没有留下审核人和时间",
        [
            claim.id
            for claim in claims
            if claim.review_decision == GraphReviewDecision.APPROVED
            and (not claim.medical_reviewed_by or claim.medical_reviewed_at is None)
        ],
    )

    expected_revision = (
        await db.scalar(select(func.max(GraphPublicationJob.target_revision)))
    ) or 0
    last_published = await db.scalar(
        select(func.max(GraphPublicationJob.target_revision)).where(
            GraphPublicationJob.status == GraphPublicationStatus.SUCCEEDED
        )
    )
    evidence_rows = await db.scalar(select(func.count()).select_from(GraphClaimEvidence)) or 0
    return VerificationReport(
        published_claims=sum(
            1 for claim in claims if claim.status == GraphClaimStatus.PUBLISHED
        ),
        evidence_rows=int(evidence_rows),
        expected_revision=expected_revision,
        last_published_revision=last_published,
        revision_in_sync=(last_published or 0) >= expected_revision,
        issues=issues,
    )


def _concept_not_active(claim: GraphClaim, concepts: dict[UUID, GraphConcept]) -> bool:
    for concept_id in (claim.subject_concept_id, claim.object_concept_id):
        concept = concepts.get(concept_id)
        if concept is None or concept.status != GraphConceptStatus.ACTIVE:
            return True
    return False


def _count_by(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


async def _get_claim(db: AsyncSession, claim_id: UUID) -> GraphClaim:
    claim = await db.get(GraphClaim, claim_id)
    if claim is None:
        raise KnowledgeGraphReviewError(f"关系不存在：{claim_id}")
    return claim
