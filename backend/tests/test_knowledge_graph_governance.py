"""G0 冻结词表与图模型边界（谁都不许悄悄扩大图模型或把用户数据带进来）。"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_knowledge_graph_candidates import (
    claim_triples,
    create_approved_document,
    extract_document_candidates,
)

from app.db.base import Base
from app.models.knowledge_graph import (
    ConceptType,
    GraphClaim,
    GraphClaimStatus,
    GraphConcept,
    GraphConceptStatus,
    GraphReviewDecision,
)
from app.services.knowledge_graph_registry import (
    KnowledgeGraphRegistryError,
    register_concept,
    rename_concept,
)
from app.services.knowledge_graph_vocabulary import (
    KnowledgeGraphVocabularyError,
    describe_triple,
    frozen_vocabulary,
    normalize_concept_name,
    validate_triple,
)

GRAPH_TABLES = [
    "graph_claim_evidence",
    "graph_claims",
    "graph_concept_aliases",
    "graph_concepts",
    "graph_publication_jobs",
]


def test_concept_types_and_predicates_are_frozen() -> None:
    """G0：五类概念、五个 predicate，改这里等于改图模型，必须先改文档与迁移。"""

    assert [member.value for member in ConceptType] == [
        "topic",
        "symptom",
        "department",
        "red_flag",
        "self_care",
    ]
    assert frozen_vocabulary()["predicates"] == [
        "MAY_INCLUDE_SYMPTOM",
        "HAS_RED_FLAG",
        "SUGGESTS_DEPARTMENT",
        "HAS_SELF_CARE_TOPIC",
        "RELATED_TOPIC",
    ]
    predicates = frozen_vocabulary()["predicates"]
    for forbidden in ("CAUSES", "DIAGNOSES", "TREATS", "CURES", "PRESCRIBES", "DOSAGE"):
        assert forbidden not in predicates, f"predicate 不得出现会被读成医疗结论的 {forbidden}"
    assert frozen_vocabulary()["claimStatuses"] == [
        "candidate",
        "reviewed",
        "published",
        "retired",
    ]


def test_predicate_type_rules_reject_wrong_endpoints() -> None:
    validate_triple(ConceptType.TOPIC, "HAS_RED_FLAG", ConceptType.RED_FLAG)
    validate_triple(ConceptType.TOPIC, "RELATED_TOPIC", ConceptType.TOPIC)
    with pytest.raises(KnowledgeGraphVocabularyError) as wrong_object:
        validate_triple(ConceptType.TOPIC, "HAS_RED_FLAG", ConceptType.SYMPTOM)
    assert "宾语只能是 red_flag" in str(wrong_object.value)
    with pytest.raises(KnowledgeGraphVocabularyError) as wrong_subject:
        validate_triple(ConceptType.SYMPTOM, "MAY_INCLUDE_SYMPTOM", ConceptType.SYMPTOM)
    assert "主语只能是 topic" in str(wrong_subject.value)
    with pytest.raises(KnowledgeGraphVocabularyError) as unknown:
        validate_triple(ConceptType.TOPIC, "CAUSES", ConceptType.TOPIC)
    assert "未知关系类型" in str(unknown.value)


def test_normalize_concept_name_handles_cjk_spacing_and_width() -> None:
    assert normalize_concept_name("肺 癌") == normalize_concept_name("肺癌")
    assert normalize_concept_name("（肺癌）") == normalize_concept_name("肺癌")
    assert normalize_concept_name("ＮＳＣＬＣ") == normalize_concept_name("nsclc")
    assert normalize_concept_name("  咳嗽，") == normalize_concept_name("咳嗽")
    with pytest.raises(KnowledgeGraphVocabularyError):
        normalize_concept_name("  ，。 ")


def test_graph_tables_never_reference_user_data() -> None:
    """硬边界：图谱表只能引用别的图谱表与**公共**知识表。"""

    present = [name for name in Base.metadata.tables if name.startswith("graph_")]
    assert sorted(present) == GRAPH_TABLES
    for table_name in GRAPH_TABLES:
        table = Base.metadata.tables[table_name]
        for foreign_key in table.foreign_keys:
            target = foreign_key.column.table.name
            assert target.startswith(("graph_", "knowledge_")), (
                f"{table_name} 引用了不允许的表：{target}"
            )
        for column in table.columns:
            assert column.name not in {
                "user_id",
                "consultation_id",
                "message_id",
                "health_record_id",
                "private_knowledge_collection_id",
            }, f"{table_name} 出现了用户数据列：{column.name}"
    # 反向也要成立：图谱是投影，业务表不得反过来依赖它。
    for table in Base.metadata.tables.values():
        if table.name.startswith("graph_"):
            continue
        for foreign_key in table.foreign_keys:
            assert not foreign_key.column.table.name.startswith("graph_")


async def test_register_concept_is_idempotent_and_keeps_id_on_rename(profile_context) -> None:
    _, db, _ = profile_context
    first = await register_concept(
        db,
        concept_type=ConceptType.TOPIC,
        canonical_name="肺癌",
        aliases=["肺 癌", "支气管肺癌", "肺癌"],
    )
    assert first.created is True
    assert first.aliases_added == ["支气管肺癌"]
    # 「肺 癌」规范化后与规范名相同、「肺癌」与规范名相同，重复别名不重复入库。
    assert first.aliases_skipped == ["肺 癌", "肺癌"]

    again = await register_concept(db, concept_type=ConceptType.TOPIC, canonical_name="肺癌")
    assert again.created is False
    assert again.concept_id == first.concept_id
    assert again.renamed is False

    renamed = await rename_concept(db, first.concept_id, canonical_name="原发性支气管肺癌")
    assert renamed.concept_id == first.concept_id, "规范名变更不得改变概念 ID"
    assert renamed.renamed is True
    assert renamed.aliases_added == ["肺癌"], "旧规范名必须留成别名，否则正文里的旧名会失配"


async def test_register_refuses_name_that_is_someone_elses_alias(profile_context) -> None:
    """规范名撞到别人的别名时报错，不静默造重复概念。"""

    _, db, _ = profile_context
    await register_concept(
        db, concept_type=ConceptType.TOPIC, canonical_name="肺癌", aliases=["支气管肺癌"]
    )
    with pytest.raises(KnowledgeGraphRegistryError) as excinfo:
        await register_concept(db, concept_type=ConceptType.TOPIC, canonical_name="支气管肺癌")
    assert "已经是概念「肺癌」的别名" in str(excinfo.value)
    assert len((await db.scalars(select(GraphConcept))).all()) == 1


async def test_rename_keeps_history_and_old_name_still_matches(profile_context) -> None:
    """改名后：旧 claim 仍挂在同一个概念上，正文里的旧名照样能抽出同一条关系。"""

    _, db, _ = profile_context
    await register_concept(db, concept_type=ConceptType.TOPIC, canonical_name="肺癌")
    await register_concept(db, concept_type=ConceptType.SYMPTOM, canonical_name="咳嗽")
    document, _ = await create_approved_document(db, ["肺癌的常见表现包括咳嗽。"])
    await extract_document_candidates(db, document.id)
    concept_id = await db.scalar(
        select(GraphConcept.id).where(GraphConcept.canonical_name == "肺癌")
    )

    await rename_concept(db, concept_id, canonical_name="原发性支气管肺癌")

    claims = (await db.scalars(select(GraphClaim))).all()
    assert {claim.subject_concept_id for claim in claims} == {concept_id}, "历史关系不得换指向"
    assert await claim_triples(db) == {("原发性支气管肺癌", "MAY_INCLUDE_SYMPTOM", "咳嗽")}
    renamed_document, _ = await create_approved_document(db, ["肺癌的常见表现包括咳嗽。"])
    again = await extract_document_candidates(db, renamed_document.id)
    assert again.candidates_existing == 1, "旧名已留成别名，再次抽取应命中同一条关系"


async def test_retired_concept_is_not_resurrected_by_registration(profile_context) -> None:
    _, db, _ = profile_context
    created = await register_concept(
        db, concept_type=ConceptType.SYMPTOM, canonical_name="测试症状甲"
    )
    concept = await db.get(GraphConcept, created.concept_id)
    concept.status = GraphConceptStatus.RETIRED
    await db.flush()
    with pytest.raises(KnowledgeGraphRegistryError) as excinfo:
        await register_concept(db, concept_type=ConceptType.SYMPTOM, canonical_name="测试症状甲")
    assert "已停用" in str(excinfo.value)


async def test_database_check_constraints_reject_illegal_claims(profile_context) -> None:
    """数据库层也要拦住非法状态，而不是只靠服务层自觉。"""

    _, db, _ = profile_context
    topic = await register_concept(db, concept_type=ConceptType.TOPIC, canonical_name="约束主题")
    symptom = await register_concept(
        db, concept_type=ConceptType.SYMPTOM, canonical_name="约束症状"
    )
    now = datetime.now(UTC)

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                GraphClaim(
                    subject_concept_id=topic.concept_id,
                    predicate="CAUSES",
                    object_concept_id=symptom.concept_id,
                    extraction_version="test",
                )
            )
            await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                GraphClaim(
                    subject_concept_id=symptom.concept_id,
                    predicate="MAY_INCLUDE_SYMPTOM",
                    object_concept_id=symptom.concept_id,
                    extraction_version="test",
                )
            )
            await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                GraphClaim(
                    subject_concept_id=topic.concept_id,
                    predicate="MAY_INCLUDE_SYMPTOM",
                    object_concept_id=symptom.concept_id,
                    status=GraphClaimStatus.PUBLISHED,
                    review_decision=GraphReviewDecision.PENDING,
                    published_revision=1,
                    published_at=now,
                    extraction_version="test",
                )
            )
            await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                GraphClaim(
                    subject_concept_id=topic.concept_id,
                    predicate="MAY_INCLUDE_SYMPTOM",
                    object_concept_id=symptom.concept_id,
                    review_decision=GraphReviewDecision.APPROVED,
                    status=GraphClaimStatus.REVIEWED,
                    extraction_version="test",
                )
            )
            await db.flush()


def test_describe_triple_keeps_raw_predicate_for_audit() -> None:
    text = describe_triple("肺癌", "MAY_INCLUDE_SYMPTOM", "咳嗽")
    assert "肺癌" in text and "咳嗽" in text
    assert "MAY_INCLUDE_SYMPTOM" in text
    assert "可能出现的表现" in text