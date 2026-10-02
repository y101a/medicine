"""规则式候选抽取（G1；只从已审核公共知识块生成候选，不自动发布）。

刻意**不调用任何模型**：

- 候选的每一条都能说清「从哪个知识块的哪一段文字来的」，这一点必须确定可复现；
- 模型抽取属于 plan 第 7.1 节里「规则/模型只生成候选」的另一条支路，接入前要先有
  冻结的评测集，而评测集在 G0 里只是小型金标准，不足以支撑模型上线；
- 也避免在没有审核界面的阶段产生付费调用。

抽取只认**已登记的概念与别名**：没有登记的概念不会凭空造出生产节点（plan 第 7.1 节），
这类知识块会被列进 `chunks_without_concepts`，交给人去登记概念。
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.knowledge_graph import (
    ConceptType,
    GraphClaim,
    GraphClaimEvidence,
    GraphClaimPredicate,
    GraphClaimStatus,
    GraphConcept,
    GraphConceptAlias,
    GraphConceptStatus,
    GraphExtractionSource,
    GraphReviewDecision,
)
from app.services.knowledge_graph_vocabulary import (
    KnowledgeGraphVocabularyError,
    normalize_with_offsets,
    validate_triple,
)

#: 规则抽取器的版本。改了匹配或配对规则就必须改它，否则无法解释历史候选的来源。
RULES_EXTRACTION_VERSION = "rule_v1"

_APPROVED_DOCUMENT_STATUS = "approved"


class KnowledgeGraphExtractionError(ValueError):
    """抽取前提不成立：文档未审核通过、文档不存在等。"""


@dataclass(slots=True)
class ConceptMention:
    concept_id: UUID
    concept_type: str
    canonical_name: str
    start: int
    end: int


@dataclass(slots=True)
class CandidateExtractionResult:
    document_id: UUID
    document_title: str
    review_status: str
    chunks_scanned: int
    concepts_registered: int
    candidates_created: int
    candidates_existing: int
    evidence_added: int
    claims_skipped_not_pending: int
    chunks_without_concepts: list[UUID] = field(default_factory=list)
    dry_run: bool = False


@dataclass(slots=True)
class BatchExtractionResult:
    documents: list[CandidateExtractionResult] = field(default_factory=list)
    skipped_documents: int = 0

    @property
    def candidates_created(self) -> int:
        return sum(item.candidates_created for item in self.documents)

    @property
    def candidates_existing(self) -> int:
        return sum(item.candidates_existing for item in self.documents)


class ConceptMatcher:
    """已登记概念/别名的匹配器：最长匹配优先，命中即跳过该片段。"""

    def __init__(self, entries: dict[str, list[GraphConcept]]) -> None:
        self._entries = entries
        self._terms = sorted(entries, key=len, reverse=True)

    @property
    def term_count(self) -> int:
        return len(self._terms)

    def match(self, text: str) -> list[ConceptMention]:
        """返回按概念去重后的提及列表（每个概念取本块内第一次出现的位置）。"""

        normalized, offsets = normalize_with_offsets(text)
        mentions: dict[UUID, ConceptMention] = {}
        position = 0
        length = len(normalized)
        while position < length:
            matched_term: str | None = None
            for term in self._terms:
                if normalized.startswith(term, position):
                    matched_term = term
                    break
            if matched_term is None:
                position += 1
                continue
            end = position + len(matched_term)
            for concept in self._entries[matched_term]:
                mentions.setdefault(
                    concept.id,
                    ConceptMention(
                        concept_id=concept.id,
                        concept_type=concept.concept_type,
                        canonical_name=concept.canonical_name,
                        start=offsets[position],
                        end=offsets[end - 1] + 1,
                    ),
                )
            position = end
        return list(mentions.values())


async def load_concept_matcher(db: AsyncSession) -> ConceptMatcher:
    """载入全部**在用**概念与别名。

    公共治理词表是人工维护的小集合，一次装进内存比逐块查库更省事，也让匹配结果稳定。
    """

    concepts = list(
        (
            await db.scalars(
                select(GraphConcept).where(GraphConcept.status == GraphConceptStatus.ACTIVE)
            )
        ).all()
    )
    by_id = {concept.id: concept for concept in concepts}
    entries: dict[str, list[GraphConcept]] = {}
    for concept in concepts:
        entries.setdefault(concept.normalized_name, []).append(concept)
    aliases = list(
        (
            await db.scalars(
                select(GraphConceptAlias).where(
                    GraphConceptAlias.status == GraphConceptStatus.ACTIVE
                )
            )
        ).all()
    )
    for alias in aliases:
        concept = by_id.get(alias.concept_id)
        if concept is None:
            continue
        entries.setdefault(alias.normalized_text, []).append(concept)
    return ConceptMatcher(entries)


def _pair_candidates(
    mentions: list[ConceptMention],
) -> list[tuple[ConceptMention, str, ConceptMention]]:
    """按概念类型配对出候选三元组（predicate 由类型组合唯一决定）。"""

    topics = [item for item in mentions if item.concept_type == ConceptType.TOPIC]
    others = [item for item in mentions if item.concept_type != ConceptType.TOPIC]
    pairs: list[tuple[ConceptMention, str, ConceptMention]] = []
    for topic in topics:
        for other in others:
            predicate = _predicate_for(other.concept_type)
            if predicate is None:
                continue
            pairs.append((topic, predicate, other))
    # 相关主题是对称关系：每对只保留一条，方向按规范名排序，避免 A→B 与 B→A 两条重复。
    for index, left in enumerate(topics):
        for right in topics[index + 1 :]:
            first, second = sorted((left, right), key=lambda item: item.canonical_name)
            pairs.append((first, GraphClaimPredicate.RELATED_TOPIC, second))
    return pairs


def _predicate_for(concept_type: str) -> str | None:
    mapping = {
        ConceptType.SYMPTOM: GraphClaimPredicate.MAY_INCLUDE_SYMPTOM,
        ConceptType.RED_FLAG: GraphClaimPredicate.HAS_RED_FLAG,
        ConceptType.DEPARTMENT: GraphClaimPredicate.SUGGESTS_DEPARTMENT,
        ConceptType.SELF_CARE: GraphClaimPredicate.HAS_SELF_CARE_TOPIC,
    }
    return mapping.get(ConceptType(concept_type))


async def extract_document_candidates(
    db: AsyncSession,
    document_id: UUID,
    *,
    dry_run: bool = False,
) -> CandidateExtractionResult:
    """为**一篇已审核文档**生成候选关系（幂等：同一三元组只建一条 claim）。"""

    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise KnowledgeGraphExtractionError(f"文档不存在：{document_id}")
    if document.review_status != _APPROVED_DOCUMENT_STATUS:
        raise KnowledgeGraphExtractionError(
            f"文档「{document.title}」的审核状态是 {document.review_status}，"
            "只有 approved 的公共文档能产生候选关系"
        )

    matcher = await load_concept_matcher(db)
    chunks = list(
        (
            await db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document_id)
                .order_by(KnowledgeChunk.chunk_index)
            )
        ).all()
    )

    existing_claims = {
        (claim.subject_concept_id, claim.predicate, claim.object_concept_id): claim
        for claim in (await db.scalars(select(GraphClaim))).all()
    }
    existing_evidence = {
        (claim_id, chunk_id)
        for claim_id, chunk_id in (
            await db.execute(select(GraphClaimEvidence.claim_id, GraphClaimEvidence.chunk_id))
        ).all()
    }

    created: dict[tuple[UUID, str, UUID], GraphClaim] = {}
    planned: set[tuple[UUID, str, UUID]] = set()
    created_evidence: set[tuple[UUID, UUID]] = set()
    result = CandidateExtractionResult(
        document_id=document.id,
        document_title=document.title,
        review_status=document.review_status,
        chunks_scanned=len(chunks),
        concepts_registered=matcher.term_count,
        candidates_created=0,
        candidates_existing=0,
        evidence_added=0,
        claims_skipped_not_pending=0,
        dry_run=dry_run,
    )

    for chunk in chunks:
        mentions = matcher.match(chunk.content)
        if not mentions:
            result.chunks_without_concepts.append(chunk.id)
            continue
        for subject, predicate, object_ in _pair_candidates(mentions):
            if subject.concept_id == object_.concept_id:
                continue
            try:
                validate_triple(subject.concept_type, predicate, object_.concept_type)
            except KnowledgeGraphVocabularyError as exc:  # pragma: no cover - 规则与词表同源
                raise KnowledgeGraphExtractionError(str(exc)) from exc
            key = (subject.concept_id, predicate, object_.concept_id)
            claim = created.get(key) or existing_claims.get(key)
            if claim is None:
                if key in planned:
                    # dry_run 下同一个三元组会在多个块里重复命中，只计一次。
                    continue
                planned.add(key)
                result.candidates_created += 1
                if dry_run:
                    continue
                claim = GraphClaim(
                    subject_concept_id=subject.concept_id,
                    predicate=predicate,
                    object_concept_id=object_.concept_id,
                    status=GraphClaimStatus.CANDIDATE,
                    review_decision=GraphReviewDecision.PENDING,
                    extraction_source=GraphExtractionSource.RULE,
                    extraction_model=None,
                    extraction_version=RULES_EXTRACTION_VERSION,
                )
                db.add(claim)
                await db.flush()
                created[key] = claim
            elif claim.status != GraphClaimStatus.CANDIDATE or (
                claim.review_decision != GraphReviewDecision.PENDING
            ):
                # 已拒绝/退回/已发布的关系不因再次抽取而复活，只记数。
                result.claims_skipped_not_pending += 1
            else:
                result.candidates_existing += 1

            if dry_run:
                continue
            evidence_key = (claim.id, chunk.id)
            if evidence_key in existing_evidence or evidence_key in created_evidence:
                continue
            db.add(
                GraphClaimEvidence(
                    claim_id=claim.id,
                    chunk_id=chunk.id,
                    document_id=document.id,
                    chunk_content_hash=chunk.content_hash,
                    span_start=min(subject.start, object_.start),
                    span_end=max(subject.end, object_.end),
                )
            )
            created_evidence.add(evidence_key)
            result.evidence_added += 1

    if not dry_run:
        await db.flush()
    return result


async def extract_approved_candidates(
    db: AsyncSession,
    *,
    limit: int = 20,
    dry_run: bool = False,
) -> BatchExtractionResult:
    """为一批已审核文档生成候选（CLI 的 `extract-candidates --all-approved`）。"""

    documents = list(
        (
            await db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.review_status == _APPROVED_DOCUMENT_STATUS)
                .order_by(KnowledgeDocument.created_at)
                .limit(limit)
            )
        ).all()
    )
    batch = BatchExtractionResult()
    for document in documents:
        batch.documents.append(
            await extract_document_candidates(db, document.id, dry_run=dry_run)
        )
    return batch