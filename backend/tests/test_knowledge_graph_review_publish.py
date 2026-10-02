"""审核门槛、发布 outbox 与 verify 硬门槛。

这里的断言全部对应 plan 第 12.1/15 节：没有有效证据不能发布、来源失效必须撤回、
PG 期望 revision 与图已投影 revision 不一致时不许宣称图谱可用。
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_knowledge_graph_candidates import (
    GOLD_CORPUS,
    create_approved_document,
    register_gold_concepts,
)

from app.models.knowledge_graph import (
    ConceptType,
    GraphClaim,
    GraphClaimEvidence,
    GraphClaimStatus,
    GraphConcept,
    GraphConceptStatus,
    GraphPublicationJob,
    GraphPublicationStatus,
    GraphReviewDecision,
)
from app.services.knowledge_graph_candidates import extract_document_candidates
from app.services.knowledge_graph_publication import (
    MAX_PUBLICATION_ATTEMPTS,
    KnowledgeGraphPublicationError,
    claim_next_job,
    complete_job,
    enqueue_publication,
    fail_job,
    publication_status,
)
from app.services.knowledge_graph_registry import register_concept
from app.services.knowledge_graph_review import (
    KnowledgeGraphReviewError,
    approve_claim,
    bind_evidence,
    graph_status,
    list_review_queue,
    reject_claim,
    retire_claim,
    retire_stale_claims,
    return_claim,
    verify_graph,
)


async def candidate_claims(db) -> list[GraphClaim]:
    return list(
        (
            await db.scalars(
                select(GraphClaim).where(GraphClaim.status == GraphClaimStatus.CANDIDATE)
            )
        ).all()
    )


async def all_claims(db) -> list[GraphClaim]:
    return list((await db.scalars(select(GraphClaim))).all())


async def concepts_by_name(db) -> dict[str, GraphConcept]:
    return {
        concept.canonical_name: concept
        for concept in (await db.scalars(select(GraphConcept))).all()
    }


async def approve_all_candidates(db, *, reviewer: str = "医学测试员") -> list[UUID]:
    approved: list[UUID] = []
    for claim in await candidate_claims(db):
        await approve_claim(db, claim.id, reviewer=reviewer, note="与原文一致")
        approved.append(claim.id)
    return approved


async def extracted_fixture(db):
    await register_gold_concepts(db)
    document, chunks = await create_approved_document(db, GOLD_CORPUS)
    await extract_document_candidates(db, document.id)
    return document, chunks


async def test_review_queue_shows_description_excerpt_and_blocking_reason(
    profile_context,
) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)

    queue = await list_review_queue(db, limit=10)

    assert len(queue) == 5
    labels = ("可能出现的表现", "红旗", "科室", "自我照护")
    for item in queue:
        assert item.publishable is True
        assert item.blocking_reason is None
        assert item.evidence and item.evidence[0].excerpt
        assert item.evidence[0].valid is True
        assert item.extraction_source == "rule"
        assert any(label in item.description for label in labels)
    assert await list_review_queue(db, limit=10, decision="returned") == []


async def test_approve_requires_valid_evidence(profile_context) -> None:
    _, db, _ = profile_context
    await register_concept(db, concept_type=ConceptType.TOPIC, canonical_name="无证据主题")
    await register_concept(db, concept_type=ConceptType.SYMPTOM, canonical_name="无证据症状")
    concepts = await concepts_by_name(db)
    orphan = GraphClaim(
        subject_concept_id=concepts["无证据主题"].id,
        predicate="MAY_INCLUDE_SYMPTOM",
        object_concept_id=concepts["无证据症状"].id,
        extraction_version="test",
    )
    db.add(orphan)
    await db.flush()

    with pytest.raises(KnowledgeGraphReviewError) as excinfo:
        await approve_claim(db, orphan.id, reviewer="医学测试员")

    assert "没有任何证据" in str(excinfo.value)
    assert orphan.status == GraphClaimStatus.CANDIDATE
    assert orphan.review_decision == GraphReviewDecision.PENDING


async def test_approve_blocked_by_superseded_document(profile_context) -> None:
    _, db, _ = profile_context
    document, _ = await extracted_fixture(db)
    claim = (await candidate_claims(db))[0]
    document.review_status = "superseded"
    await db.flush()

    with pytest.raises(KnowledgeGraphReviewError) as excinfo:
        await approve_claim(db, claim.id, reviewer="医学测试员")

    assert "来源文档状态是 superseded" in str(excinfo.value)


async def test_approve_blocked_when_chunk_content_changed(profile_context) -> None:
    _, db, _ = profile_context
    _, chunks = await extracted_fixture(db)
    claim = (await candidate_claims(db))[0]
    chunks[0].content_hash = "b" * 64
    await db.flush()

    with pytest.raises(KnowledgeGraphReviewError) as excinfo:
        await approve_claim(db, claim.id, reviewer="医学测试员")

    assert "知识块正文已变更" in str(excinfo.value)


async def test_approve_blocked_when_concept_retired(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    claim = (await candidate_claims(db))[0]
    concepts = await concepts_by_name(db)
    concepts["肺癌"].status = GraphConceptStatus.RETIRED
    await db.flush()

    with pytest.raises(KnowledgeGraphReviewError) as excinfo:
        await approve_claim(db, claim.id, reviewer="医学测试员")

    assert "已停用" in str(excinfo.value)


async def test_approve_records_reviewer_and_time(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    claim = (await candidate_claims(db))[0]

    result = await approve_claim(db, claim.id, reviewer=" 李医生 ", note="核对过原文")

    assert result.status == GraphClaimStatus.REVIEWED
    assert result.review_decision == GraphReviewDecision.APPROVED
    assert result.valid_evidence_count >= 1
    await db.refresh(claim)
    assert claim.medical_reviewed_by == "李医生"
    assert claim.medical_reviewed_at is not None
    assert claim.review_note == "核对过原文"
    assert claim.published_revision is None


async def test_reject_and_return_keep_claim_as_candidate(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    claims = await candidate_claims(db)

    rejected = await reject_claim(db, claims[0].id, reviewer="李医生", note="表述不一致")
    returned = await return_claim(db, claims[1].id, reviewer="李医生", note="请补充来源")

    assert rejected.review_decision == GraphReviewDecision.REJECTED
    assert returned.review_decision == GraphReviewDecision.RETURNED
    await db.refresh(claims[0])
    await db.refresh(claims[1])
    assert claims[0].status == GraphClaimStatus.CANDIDATE
    assert claims[1].status == GraphClaimStatus.CANDIDATE
    with pytest.raises(KnowledgeGraphReviewError) as empty_note:
        await reject_claim(db, claims[2].id, reviewer="李医生", note="   ")
    assert "原因不能为空" in str(empty_note.value)
    with pytest.raises(KnowledgeGraphReviewError):
        await return_claim(db, claims[2].id, reviewer="   ", note="有原因但没写审核人")


async def test_publish_pipeline_end_to_end(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)

    result = await enqueue_publication(db, actor="医学测试员")

    assert result.revision == 1
    assert result.claim_count == 5
    assert result.idempotency_key == "graph-revision:1"
    claims = await all_claims(db)
    assert {claim.status for claim in claims} == {GraphClaimStatus.PUBLISHED}
    assert {claim.published_revision for claim in claims} == {1}
    assert all(claim.published_at is not None for claim in claims)
    job = await db.get(GraphPublicationJob, result.job_id)
    assert job.status == GraphPublicationStatus.QUEUED
    assert job.claim_count == 5
    assert job.attempts == 0

    report = await verify_graph(db)
    assert report.issues == [], report.issues
    assert report.published_claims == 5
    assert report.expected_revision == 1
    assert report.last_published_revision is None
    assert report.revision_in_sync is False, "还没投影完，不许算同步"

    leased = await claim_next_job(db, owner="graph-worker-1", lease_seconds=60)
    assert leased is not None
    assert leased.target_revision == 1
    assert leased.attempts == 1
    await complete_job(db, leased.job_id, owner="graph-worker-1")

    await db.refresh(job)
    assert job.status == GraphPublicationStatus.SUCCEEDED
    assert job.finished_at is not None
    assert job.lease_owner is None
    finished = await verify_graph(db)
    assert finished.revision_in_sync is True
    assert (await publication_status(db)).last_published_revision == 1
    assert await claim_next_job(db, owner="graph-worker-2") is None


async def test_second_publish_only_carries_new_claims(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    first = await enqueue_publication(db, actor="医学测试员")

    with pytest.raises(KnowledgeGraphPublicationError) as excinfo:
        await enqueue_publication(db, actor="医学测试员")
    assert "没有可发布的已审核关系" in str(excinfo.value)

    await register_concept(db, concept_type=ConceptType.SELF_CARE, canonical_name="规律随访")
    extra_document, _ = await create_approved_document(db, ["肺癌患者应重视规律随访。"])
    await extract_document_candidates(db, extra_document.id)
    await approve_all_candidates(db)

    second = await enqueue_publication(db, actor="医学测试员")

    assert first.revision == 1
    assert second.revision == 2
    assert second.claim_count == 1
    by_revision: dict[int | None, list[GraphClaim]] = {}
    for claim in await all_claims(db):
        by_revision.setdefault(claim.published_revision, []).append(claim)
    assert set(by_revision) == {1, 2}
    assert len(by_revision[1]) == 5
    newest = by_revision[2][0]
    concepts = await concepts_by_name(db)
    assert concepts_by_name_names(concepts, newest) == ("肺癌", "规律随访")


def concepts_by_name_names(concepts: dict[str, GraphConcept], claim: GraphClaim) -> tuple:
    """把 claim 两端换回名字（方便断言）。"""

    by_id = {concept.id: name for name, concept in concepts.items()}
    return by_id[claim.subject_concept_id], by_id[claim.object_concept_id]


async def test_failed_job_is_retried_then_gives_up(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    published = await enqueue_publication(db, actor="医学测试员")

    for attempt in range(1, MAX_PUBLICATION_ATTEMPTS + 1):
        leased = await claim_next_job(db, owner="graph-worker-1")
        assert leased is not None, f"第 {attempt} 次应当还能重试"
        assert leased.attempts == attempt
        await fail_job(
            db,
            leased.job_id,
            owner="graph-worker-1",
            error_code="NEO4J_UNAVAILABLE",
            error_message="连接被拒绝",
        )

    assert await claim_next_job(db, owner="graph-worker-1") is None, "超过上限就停手"
    job = await db.get(GraphPublicationJob, published.job_id)
    assert job.status == GraphPublicationStatus.FAILED
    assert job.error_code == "NEO4J_UNAVAILABLE"
    assert job.attempts == MAX_PUBLICATION_ATTEMPTS
    report = await verify_graph(db)
    assert report.issues == [], "投影失败不回滚已审核事实，也不算数据违规"
    assert report.revision_in_sync is False


async def test_lease_belongs_to_one_worker(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    await enqueue_publication(db, actor="医学测试员")
    leased = await claim_next_job(db, owner="graph-worker-1")
    assert leased is not None

    with pytest.raises(KnowledgeGraphPublicationError) as excinfo:
        await complete_job(db, leased.job_id, owner="graph-worker-2")
    assert "租约不属于 graph-worker-2" in str(excinfo.value)
    with pytest.raises(KnowledgeGraphPublicationError):
        await claim_next_job(db, owner="   ")
    with pytest.raises(KnowledgeGraphPublicationError):
        await claim_next_job(db, owner="graph-worker-1", lease_seconds=0)


async def test_retire_published_claim_keeps_row_and_revision(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    await enqueue_publication(db, actor="医学测试员")
    target = (await all_claims(db))[0]

    result = await retire_claim(db, target.id, reviewer="李医生", reason="来源已更新，先下线")

    assert result.status == GraphClaimStatus.RETIRED
    await db.refresh(target)
    assert target.retired_by == "李医生"
    assert target.retire_reason == "来源已更新，先下线"
    assert target.retired_at is not None
    assert target.published_revision == 1, "撤回不删行，revision 记录留着"
    with pytest.raises(KnowledgeGraphReviewError):
        await retire_claim(db, target.id, reviewer="李医生", reason="再来一次")
    report = await verify_graph(db)
    assert report.issues == []
    assert report.published_claims == 4
    assert (await graph_status(db)).claims_by_status == {"published": 4, "retired": 1}


async def test_retire_candidate_is_rejected(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    claim = (await candidate_claims(db))[0]

    with pytest.raises(KnowledgeGraphReviewError) as excinfo:
        await retire_claim(db, claim.id, reviewer="李医生", reason="候选不该走撤回")

    assert "只能撤回已审核或已发布的关系" in str(excinfo.value)


async def test_verify_detects_hash_drift_after_publication(profile_context) -> None:
    _, db, _ = profile_context
    _, chunks = await extracted_fixture(db)
    await approve_all_candidates(db)
    await enqueue_publication(db, actor="医学测试员")
    chunks[0].content_hash = "c" * 64
    await db.flush()

    report = await verify_graph(db)

    assert report.ok is False
    codes = {issue.code for issue in report.issues}
    assert "EVIDENCE_HASH_MISMATCH" in codes
    assert "LIVE_WITHOUT_VALID_EVIDENCE" in codes
    status = await graph_status(db)
    assert status.stale_live_claims == 5

    retired = await retire_stale_claims(db, reviewer="李医生")

    assert len(retired) == 5
    assert (await verify_graph(db)).issues == []
    assert (await graph_status(db)).stale_live_claims == 0


async def test_verify_detects_superseded_source_and_retire_stale_fixes_it(
    profile_context,
) -> None:
    _, db, _ = profile_context
    document, _ = await extracted_fixture(db)
    await approve_all_candidates(db)
    await enqueue_publication(db, actor="医学测试员")
    document.review_status = "superseded"
    await db.flush()

    report = await verify_graph(db)
    codes = {issue.code for issue in report.issues}
    assert "EVIDENCE_DOCUMENT_NOT_APPROVED" in codes
    assert report.ok is False

    retired = await retire_stale_claims(db, reviewer="李医生", reason="来源被替代")

    assert len(retired) == 5
    assert (await verify_graph(db)).issues == []


async def test_verify_detects_retired_concept_on_live_claim(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    concepts = await concepts_by_name(db)
    concepts["胸外科"].status = GraphConceptStatus.RETIRED
    await db.flush()

    report = await verify_graph(db)

    assert "LIVE_CLAIM_USES_RETIRED_CONCEPT" in {issue.code for issue in report.issues}
    assert report.ok is False


async def test_bind_evidence_manual_path_and_duplicate_guard(profile_context) -> None:
    _, db, _ = profile_context
    _, chunks = await extracted_fixture(db)
    await register_concept(db, concept_type=ConceptType.SELF_CARE, canonical_name="规律复查")
    concepts = await concepts_by_name(db)
    claim = GraphClaim(
        subject_concept_id=concepts["肺癌"].id,
        predicate="HAS_SELF_CARE_TOPIC",
        object_concept_id=concepts["规律复查"].id,
        extraction_version="manual",
    )
    db.add(claim)
    await db.flush()

    evidence_id = await bind_evidence(db, claim.id, chunks[1].id, span_start=0, span_end=6)

    evidence = await db.get(GraphClaimEvidence, evidence_id)
    assert evidence.document_id == chunks[1].document_id
    assert evidence.chunk_content_hash == chunks[1].content_hash
    with pytest.raises(KnowledgeGraphReviewError) as duplicate:
        await bind_evidence(db, claim.id, chunks[1].id)
    assert "已经绑过了" in str(duplicate.value)
    with pytest.raises(KnowledgeGraphReviewError):
        await bind_evidence(db, claim.id, uuid4())

    approved = await approve_claim(db, claim.id, reviewer="李医生")

    assert approved.status == GraphClaimStatus.REVIEWED


async def test_graph_status_reports_counts_and_revisions(profile_context) -> None:
    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    await enqueue_publication(db, actor="医学测试员")

    status = await graph_status(db)

    assert status.concepts_by_type == {
        "topic": 1,
        "symptom": 2,
        "red_flag": 1,
        "department": 1,
        "self_care": 1,
    }
    assert status.claims_by_status == {"published": 5}
    assert status.claims_by_decision == {"approved": 5}
    assert status.live_claims == 5
    assert status.stale_live_claims == 0
    assert status.evidence_rows == 5
    assert status.expected_revision == 1
    assert status.last_published_revision is None
    assert status.last_job_status is None