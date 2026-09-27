import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.rag.evaluation import (
    EvaluationCase,
    RetrievalEvaluationError,
    load_evaluation_set,
    run_prototype_evaluation,
    score_case,
)
from app.rag.retrieval import RetrievalCitation, RetrievalResult


def citation(slug: str, similarity: float = 0.8) -> RetrievalCitation:
    return RetrievalCitation(
        chunk_id=uuid4(),
        document_id=uuid4(),
        source_key="developer_prototype_knowledge",
        organization="项目开发者",
        title=slug,
        canonical_url=f"https://prototype.invalid/medical-knowledge/{slug}",
        section_title="测试",
        version_label="prototype-test",
        published_at=datetime.now(UTC),
        content="隔离测试内容",
        similarity=similarity,
        trust_level="prototype",
    )


def test_independent_dataset_covers_every_prototype_document():
    """独立题集必须覆盖全部原型语料：新增语料却没补题时，这条会失败提醒。"""
    backend_root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (backend_root / "data" / "prototype_knowledge" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    corpus_slugs = {entry["slug"] for entry in manifest["documents"]}
    evaluation_set = load_evaluation_set(
        backend_root / "docs" / "medical_retrieval_evaluation_independent.json"
    )
    covered = {
        slug for case in evaluation_set.cases for slug in case.expected_document_slugs
    }

    assert len(evaluation_set.cases) >= 15
    assert corpus_slugs <= covered, (
        f"以下原型语料没有对应评测题：{sorted(corpus_slugs - covered)}"
    )


def test_score_case_records_expected_document_rank():
    case = EvaluationCase(
        id="case",
        query="测试查询",
        expected_topics=["主题"],
        expected_document_slugs=["expected"],
        safety_class="education",
    )

    result = score_case(case, [citation("other", 0.9), citation("expected", 0.8)])

    assert result.hit is True
    assert result.matched_rank == 2
    assert result.top_similarity == 0.9
    assert result.returned_trust_levels == ("prototype", "prototype")


def test_evaluation_dataset_loads_all_cases():
    evaluation_set = load_evaluation_set()

    assert len(evaluation_set.cases) >= 10
    assert all(case.expected_document_slugs for case in evaluation_set.cases)


def test_v2_dataset_has_frozen_tune_holdout_and_negative_cases():
    backend_root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (backend_root / "data" / "prototype_knowledge" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    evaluation_set = load_evaluation_set(
        backend_root / "docs" / "medical_retrieval_evaluation_v2.json"
    )

    assert len(evaluation_set.cases) == 80
    assert sum(case.split == "tune" for case in evaluation_set.cases) == 60
    assert sum(case.split == "holdout" for case in evaluation_set.cases) == 20
    assert sum(case.case_type == "supported" for case in evaluation_set.cases) == 52
    assert sum(case.case_type == "confusable" for case in evaluation_set.cases) == 12
    assert sum(case.case_type == "unsupported" for case in evaluation_set.cases) == 16
    assert all(
        not case.expected_document_slugs
        for case in evaluation_set.cases
        if case.case_type == "unsupported"
    )
    corpus_slugs = {entry["slug"] for entry in manifest["documents"]}
    covered_slugs = {
        slug
        for case in evaluation_set.cases
        if case.case_type != "unsupported"
        for slug in case.expected_document_slugs
    }
    assert corpus_slugs <= covered_slugs


def test_case_type_and_expected_documents_must_agree():
    with pytest.raises(ValidationError, match="不应配置期望文档"):
        EvaluationCase(
            id="unsupported-with-answer",
            query="库外问题",
            expected_topics=[],
            expected_document_slugs=["asthma"],
            safety_class="education",
            case_type="unsupported",
        )

    with pytest.raises(ValidationError, match="至少配置一个期望文档"):
        EvaluationCase(
            id="supported-without-answer",
            query="库内问题",
            expected_topics=["哮喘"],
            expected_document_slugs=[],
            safety_class="education",
            case_type="supported",
        )


def test_score_case_treats_unsupported_results_as_false_positives():
    case = EvaluationCase(
        id="unsupported",
        query="手腕扭伤怎么办",
        expected_topics=[],
        expected_document_slugs=[],
        safety_class="education",
        case_type="unsupported",
        body_system="musculoskeletal",
        query_style="colloquial",
    )

    empty = score_case(case, [])
    returned = score_case(case, [citation("asthma")])

    assert empty.passed is True
    assert empty.false_positive is False
    assert returned.passed is False
    assert returned.false_positive is True
    assert returned.hit is False


async def test_evaluation_passes_the_mode_through_and_records_it(monkeypatch):
    """对比评测的前提：模式必须真的透传到检索层，并且写进报告里。"""
    from app.rag import evaluation

    async def fake_search(_db, _query: str, *, top_k: int, mode: str):
        assert top_k == 3
        assert mode == "keyword"
        return RetrievalResult(
            query_redacted=False,
            model="qwen3.7-text-embedding-flash",
            version="2026-09-01",
            items=[],
            mode="keyword",
        )

    monkeypatch.setattr(evaluation, "search_knowledge", fake_search)

    report = await run_prototype_evaluation(None, mode="keyword")  # type: ignore[arg-type]

    assert report.mode == "keyword"
    assert report.case_count >= 10
    assert report.hit_count == 0


async def test_evaluation_reports_ranking_negative_and_group_metrics(
    monkeypatch, tmp_path: Path
):
    from app.rag import evaluation

    dataset = tmp_path / "evaluation.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "rank-one",
                        "query": "rank-one",
                        "expected_topics": ["哮喘"],
                        "expected_document_slugs": ["asthma"],
                        "safety_class": "education",
                        "body_system": "respiratory",
                        "query_style": "exact_term",
                        "split": "tune",
                    },
                    {
                        "id": "rank-two",
                        "query": "rank-two",
                        "expected_topics": ["高血压"],
                        "expected_document_slugs": ["hypertension"],
                        "safety_class": "education",
                        "body_system": "cardiovascular",
                        "query_style": "colloquial",
                        "split": "holdout",
                    },
                    {
                        "id": "negative-pass",
                        "query": "negative-pass",
                        "expected_topics": [],
                        "expected_document_slugs": [],
                        "safety_class": "education",
                        "case_type": "unsupported",
                        "body_system": "musculoskeletal",
                        "query_style": "colloquial",
                        "split": "tune",
                    },
                    {
                        "id": "negative-fail",
                        "query": "negative-fail",
                        "expected_topics": [],
                        "expected_document_slugs": [],
                        "safety_class": "education",
                        "case_type": "unsupported",
                        "body_system": "dermatological",
                        "query_style": "colloquial",
                        "split": "holdout",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async def fake_search(_db, query: str, *, top_k: int, mode: str):
        assert top_k == 3
        items = {
            "rank-one": [citation("asthma")],
            "rank-two": [citation("other"), citation("hypertension")],
            "negative-pass": [],
            "negative-fail": [citation("diabetes")],
        }[query]
        return RetrievalResult(
            query_redacted=False,
            model="test",
            version="test",
            items=items,
            mode="keyword",
        )

    monkeypatch.setattr(evaluation, "search_knowledge", fake_search)

    report = await run_prototype_evaluation(
        None, dataset, mode="keyword"  # type: ignore[arg-type]
    )

    assert report.supported_case_count == 2
    assert report.unsupported_case_count == 2
    assert report.hit_count == 2
    assert report.recall_at_1 == 0.5
    assert report.recall_at_3 == 1.0
    assert report.mean_reciprocal_rank == 0.75
    assert report.unsupported_false_positive_rate == 0.5
    assert report.pass_rate == 0.75
    assert report.by_body_system["respiratory"].recall_at_1 == 1.0
    assert report.by_split["holdout"].pass_rate == 0.5

    holdout_report = await run_prototype_evaluation(
        None,  # type: ignore[arg-type]
        dataset,
        mode="keyword",
        split="holdout",
    )
    assert holdout_report.case_count == 2
    assert holdout_report.evaluation_split == "holdout"
    assert set(holdout_report.by_split) == {"holdout"}


async def test_prototype_evaluation_is_disabled_outside_development(
    monkeypatch,
):
    from app.rag import evaluation

    settings = evaluation.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(evaluation, "get_settings", lambda: settings)

    with pytest.raises(RetrievalEvaluationError, match="development"):
        await run_prototype_evaluation(None)  # type: ignore[arg-type]
