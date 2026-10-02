"""候选抽取：G0 小型金标准 + 幂等 + 证据区间必须落在原文上。"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.models.knowledge_graph import (
    ConceptType,
    GraphClaim,
    GraphClaimEvidence,
    GraphClaimStatus,
    GraphConcept,
    GraphReviewDecision,
)
from app.services.knowledge_graph_candidates import (
    RULES_EXTRACTION_VERSION,
    KnowledgeGraphExtractionError,
    extract_approved_candidates,
    extract_document_candidates,
    load_concept_matcher,
)
from app.services.knowledge_graph_registry import register_concept
from app.services.knowledge_graph_review import reject_claim

#: G0 金标准：人工判定的「这段文字只允许抽出这五条关系」。
GOLD_CORPUS = [
    "肺癌的常见表现包括咳嗽、咯血和胸痛。出现咯血应尽快到胸外科就诊。戒烟是最重要的自我照护措施。",
    "咳嗽持续两周以上，建议尽早就诊评估。",
    "本页内容正在整理中。",
]
GOLD_TRIPLES = {
    ("肺癌", "MAY_INCLUDE_SYMPTOM", "咳嗽"),
    ("肺癌", "MAY_INCLUDE_SYMPTOM", "胸痛"),
    ("肺癌", "HAS_RED_FLAG", "咯血"),
    ("肺癌", "SUGGESTS_DEPARTMENT", "胸外科"),
    ("肺癌", "HAS_SELF_CARE_TOPIC", "戒烟"),
}


async def create_approved_document(
    db, chunks: list[str], *, review_status: str = "approved"
) -> tuple[KnowledgeDocument, list[KnowledgeChunk]]:
    now = datetime.now(UTC)
    source = KnowledgeSource(
        source_key=f"kg-test-{uuid4().hex[:12]}",
        priority=1,
        organization="测试卫生机构",
        channel_name="图谱治理测试渠道",
        authority_level="test_authority",
        jurisdiction="CN",
        language="zh-CN",
        entry_url="https://www.nhc.gov.cn/test/kg.shtml",
        ingestion_status="approved",
        automated_collection=False,
    )
    db.add(source)
    await db.flush()
    document = KnowledgeDocument(
        source_id=source.id,
        canonical_url=f"https://www.nhc.gov.cn/test/kg-{uuid4().hex[:8]}.shtml",
        title="图谱候选抽取测试资料",
        content_type="markdown",
        language="zh-CN",
        jurisdiction="CN",
        published_at=now,
        version_label="test-v1",
        review_status=review_status,
        license_type="test_permission",
        legal_reviewed_at=now,
        legal_reviewed_by="版权测试员",
        medical_reviewed_at=now,
        medical_reviewed_by="医学测试员",
        content_hash="a" * 64,
        content_text="\n".join(chunks),
    )
    db.add(document)
    await db.flush()
    rows = [
        KnowledgeChunk(
            document_id=document.id,
            chunk_index=index,
            section_title=f"第 {index} 节",
            content=text,
            content_hash=f"{index:064d}",
        )
        for index, text in enumerate(chunks)
    ]
    db.add_all(rows)
    await db.flush()
    return document, rows


async def register_gold_concepts(db) -> dict[str, UUID]:
    seeds = [
        (ConceptType.TOPIC, "肺癌", ["支气管肺癌", "肺 癌", "NSCLC"]),
        (ConceptType.SYMPTOM, "咳嗽", ["咳 嗽"]),
        (ConceptType.SYMPTOM, "胸痛", []),
        (ConceptType.RED_FLAG, "咯血", ["咯 血"]),
        (ConceptType.DEPARTMENT, "胸外科", ["胸 外 科"]),
        (ConceptType.SELF_CARE, "戒烟", []),
    ]
    ids: dict[str, UUID] = {}
    for concept_type, name, aliases in seeds:
        result = await register_concept(
            db, concept_type=concept_type, canonical_name=name, aliases=aliases
        )
        ids[name] = result.concept_id
    return ids


async def claim_triples(db) -> set[tuple[str, str, str]]:
    concepts = {
        concept.id: concept.canonical_name
        for concept in (await db.scalars(select(GraphConcept))).all()
    }
    claims = (await db.scalars(select(GraphClaim))).all()
    return {
        (
            concepts[claim.subject_concept_id],
            claim.predicate,
            concepts[claim.object_concept_id],
        )
        for claim in claims
    }


def test_gold_standard_is_small_and_explicit() -> None:
    """金标准是人工写的，不是抽取器跑出来的，条数固定、可被人复核。"""

    assert len(GOLD_TRIPLES) == 5
    assert len(GOLD_CORPUS) == 3


async def test_rule_extraction_matches_gold_standard(profile_context) -> None:
    _, db, _ = profile_context
    await register_gold_concepts(db)
    document, chunks = await create_approved_document(db, GOLD_CORPUS)

    result = await extract_document_candidates(db, document.id)

    assert result.candidates_created == 5, "只允许抽出金标准里的五条关系"
    assert result.chunks_scanned == 3
    assert result.chunks_without_concepts == [chunks[2].id], "没有登记概念的知识块要报出来"
    assert await claim_triples(db) == GOLD_TRIPLES

    claims = (await db.scalars(select(GraphClaim))).all()
    assert {claim.extraction_source for claim in claims} == {"rule"}
    assert {claim.extraction_version for claim in claims} == {RULES_EXTRACTION_VERSION}
    assert {claim.status for claim in claims} == {GraphClaimStatus.CANDIDATE}
    assert {claim.review_decision for claim in claims} == {GraphReviewDecision.PENDING}
    assert all(claim.medical_reviewed_by is None for claim in claims)


async def test_evidence_spans_point_back_into_original_text(profile_context) -> None:
    """证据区间落在原文上：正文切片必须真的包含两端概念名。"""

    _, db, _ = profile_context
    await register_gold_concepts(db)
    document, chunks = await create_approved_document(db, GOLD_CORPUS)
    await extract_document_candidates(db, document.id)
    content_by_chunk = {chunk.id: chunk.content for chunk in chunks}
    hash_by_chunk = {chunk.id: chunk.content_hash for chunk in chunks}

    evidence_rows = (await db.scalars(select(GraphClaimEvidence))).all()
    assert evidence_rows, "抽到关系就必须留下证据"
    for evidence in evidence_rows:
        assert evidence.span_start is not None and evidence.span_end is not None
        excerpt = content_by_chunk[evidence.chunk_id][evidence.span_start : evidence.span_end]
        assert "肺癌" in excerpt, excerpt
        assert any(
            term in excerpt for term in ("咳嗽", "咯血", "胸痛", "胸外科", "戒烟")
        ), excerpt
        assert evidence.chunk_content_hash == hash_by_chunk[
            evidence.chunk_id
        ], "证据要记录当时的知识块哈希"
        assert evidence.document_id == document.id
        assert not hasattr(evidence, "content"), "证据不得复制正文，正文只存在 PostgreSQL 一处"


async def test_extraction_is_idempotent(profile_context) -> None:
    _, db, _ = profile_context
    await register_gold_concepts(db)
    document, _ = await create_approved_document(db, GOLD_CORPUS)

    first = await extract_document_candidates(db, document.id)
    second = await extract_document_candidates(db, document.id)

    assert first.candidates_created == 5
    assert second.candidates_created == 0
    assert second.candidates_existing == 5
    assert second.evidence_added == 0
    assert len((await db.scalars(select(GraphClaim))).all()) == 5
    assert len((await db.scalars(select(GraphClaimEvidence))).all()) == 5


async def test_rejected_candidate_is_not_resurrected_by_reextraction(profile_context) -> None:
    _, db, _ = profile_context
    await register_gold_concepts(db)
    document, _ = await create_approved_document(db, GOLD_CORPUS)
    await extract_document_candidates(db, document.id)
    concepts = {
        concept.canonical_name: concept.id
        for concept in (await db.scalars(select(GraphConcept))).all()
    }
    claim = await db.scalar(
        select(GraphClaim).where(
            GraphClaim.subject_concept_id == concepts["肺癌"],
            GraphClaim.predicate == "HAS_RED_FLAG",
        )
    )
    await reject_claim(db, claim.id, reviewer="医学测试员", note="表述与原文不一致")

    again = await extract_document_candidates(db, document.id)

    assert again.candidates_created == 0
    assert again.claims_skipped_not_pending >= 1
    await db.refresh(claim)
    assert claim.review_decision == GraphReviewDecision.REJECTED
    assert claim.status == GraphClaimStatus.CANDIDATE


async def test_unapproved_document_cannot_produce_candidates(profile_context) -> None:
    _, db, _ = profile_context
    await register_gold_concepts(db)
    document, _ = await create_approved_document(db, GOLD_CORPUS, review_status="pending")

    with pytest.raises(KnowledgeGraphExtractionError) as excinfo:
        await extract_document_candidates(db, document.id)

    assert "只有 approved" in str(excinfo.value)
    assert (await db.scalars(select(GraphClaim))).all() == []


async def test_dry_run_writes_nothing(profile_context) -> None:
    _, db, _ = profile_context
    await register_gold_concepts(db)
    document, _ = await create_approved_document(db, GOLD_CORPUS)

    result = await extract_document_candidates(db, document.id, dry_run=True)

    assert result.candidates_created == 5
    assert result.dry_run is True
    assert (await db.scalars(select(GraphClaim))).all() == []
    assert (await db.scalars(select(GraphClaimEvidence))).all() == []


async def test_alias_casefold_and_fullwidth_matching(profile_context) -> None:
    _, db, _ = profile_context
    await register_gold_concepts(db)
    document, _ = await create_approved_document(
        db, ["ＮＳＣＬＣ 的常见表现包括咳 嗽。"]
    )

    result = await extract_document_candidates(db, document.id)

    assert result.candidates_created == 1
    assert await claim_triples(db) == {("肺癌", "MAY_INCLUDE_SYMPTOM", "咳嗽")}


async def test_same_alias_on_two_concepts_yields_two_candidates(profile_context) -> None:
    """别名不全局唯一：同形别名属于两个概念时，两边都要出候选交给人判断。"""

    _, db, _ = profile_context
    await register_concept(
        db, concept_type=ConceptType.TOPIC, canonical_name="肺结节", aliases=["结节"]
    )
    await register_concept(
        db, concept_type=ConceptType.TOPIC, canonical_name="甲状腺结节", aliases=["结节"]
    )
    await register_concept(db, concept_type=ConceptType.SYMPTOM, canonical_name="咳嗽")
    document, _ = await create_approved_document(db, ["结节患者可能出现咳嗽。"])

    result = await extract_document_candidates(db, document.id)

    assert result.candidates_created == 3, "两个同形主题各出一条表现，另加一条二者相关主题"
    assert await claim_triples(db) == {
        ("肺结节", "MAY_INCLUDE_SYMPTOM", "咳嗽"),
        ("甲状腺结节", "MAY_INCLUDE_SYMPTOM", "咳嗽"),
        # 对称关系只出一条，方向按规范名排序（确定性，便于人工复核）。
        ("甲状腺结节", "RELATED_TOPIC", "肺结节"),
    }
    assert len((await db.scalars(select(GraphConcept))).all()) == 3

    matcher = await load_concept_matcher(db)
    mentions = matcher.match("结节")
    assert {mention.canonical_name for mention in mentions} == {"肺结节", "甲状腺结节"}
    assert len(mentions) <= 5, "plan 要求同形别名解析最多返回 5 个候选"


async def test_batch_extraction_skips_unapproved_documents(profile_context) -> None:
    _, db, _ = profile_context
    await register_gold_concepts(db)
    await create_approved_document(db, GOLD_CORPUS)
    await create_approved_document(db, ["肺癌的常见表现包括咳嗽。"], review_status="pending")

    batch = await extract_approved_candidates(db, limit=10)

    assert len(batch.documents) == 1, "批量模式只处理 approved 文档"
    assert batch.candidates_created == 5