from datetime import UTC, datetime
from uuid import uuid4

import pytest

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
