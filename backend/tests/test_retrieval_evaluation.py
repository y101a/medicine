import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.rag.cli import build_parser, run_relevance_gate_sweep
from app.rag.evaluation import (
    EvaluationCase,
    EvaluationCaseResult,
    RetrievalEvaluationError,
    _checkpoint_identity,
    build_report,
    load_evaluation_set,
    load_results_report,
    meets_acceptance,
    regate_case,
    run_prototype_evaluation,
    score_case,
    select_gate,
    split_report,
    sweep_gates,
)
from app.rag.relevance import (
    RelevanceGate,
    candidate_threshold_gate,
    current_consultation_gate,
    no_gate,
)
from app.rag.retrieval import RetrievalCitation, RetrievalError, RetrievalResult


def citation(
    slug: str,
    similarity: float = 0.8,
    *,
    keyword: float | None = None,
    vector: float | None = None,
) -> RetrievalCitation:
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
        keyword_score=keyword,
        vector_similarity=vector,
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
    covered = {slug for case in evaluation_set.cases for slug in case.expected_document_slugs}

    assert len(evaluation_set.cases) >= 15
    assert corpus_slugs <= covered, f"以下原型语料没有对应评测题：{sorted(corpus_slugs - covered)}"


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


async def test_evaluation_reports_ranking_negative_and_group_metrics(monkeypatch, tmp_path: Path):
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
        None,
        dataset,
        mode="keyword",  # type: ignore[arg-type]
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

    settings = evaluation.get_settings().model_copy(update={"app_environment": "production"})
    monkeypatch.setattr(evaluation, "get_settings", lambda: settings)

    with pytest.raises(RetrievalEvaluationError, match="development"):
        await run_prototype_evaluation(None)  # type: ignore[arg-type]


async def test_evaluation_retries_transient_retrieval_errors(monkeypatch):
    from app.rag import evaluation

    attempts = 0

    async def flaky_search(_db, _query: str, *, top_k: int, mode: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RetrievalError(504, "EMBEDDING_TIMEOUT", "暂时超时")
        return RetrievalResult(
            query_redacted=False,
            model="test",
            version="test",
            items=[],
            mode="vector",
        )

    async def no_wait(_seconds: float):
        return None

    monkeypatch.setattr(evaluation, "search_knowledge", flaky_search)
    monkeypatch.setattr(evaluation.asyncio, "sleep", no_wait)

    report = await run_prototype_evaluation(  # type: ignore[arg-type]
        None, mode="vector", max_retries=1
    )

    assert attempts == report.case_count + 1
    assert report.retry_count == 1


async def test_evaluation_reports_case_after_retry_exhaustion(monkeypatch):
    from app.rag import evaluation

    async def unavailable(_db, _query: str, *, top_k: int, mode: str):
        raise RetrievalError(502, "EMBEDDING_UNAVAILABLE", "暂时不可用")

    async def no_wait(_seconds: float):
        return None

    monkeypatch.setattr(evaluation, "search_knowledge", unavailable)
    monkeypatch.setattr(evaluation.asyncio, "sleep", no_wait)

    with pytest.raises(
        RetrievalEvaluationError,
        match=r"评测题 .* 检索失败（EMBEDDING_UNAVAILABLE）",
    ):
        await run_prototype_evaluation(  # type: ignore[arg-type]
            None, mode="vector", max_retries=1
        )


async def test_evaluation_checkpoint_resumes_after_failed_case(monkeypatch, tmp_path: Path):
    from app.rag import evaluation

    dataset = tmp_path / "evaluation.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "first",
                        "query": "first query",
                        "expected_document_slugs": ["asthma"],
                        "safety_class": "education",
                    },
                    {
                        "id": "second",
                        "query": "second query",
                        "expected_document_slugs": ["hypertension"],
                        "safety_class": "education",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    checkpoint = tmp_path / "checkpoint.json"
    first_run_queries: list[str] = []

    async def fails_on_second(_db, query: str, *, top_k: int, mode: str):
        first_run_queries.append(query)
        if query == "second query":
            raise RetrievalError(504, "EMBEDDING_TIMEOUT", "暂时超时")
        return RetrievalResult(False, "test", "test", [citation("asthma")], "vector")

    monkeypatch.setattr(evaluation, "search_knowledge", fails_on_second)
    with pytest.raises(RetrievalEvaluationError, match="second"):
        await run_prototype_evaluation(  # type: ignore[arg-type]
            None,
            dataset,
            mode="vector",
            max_retries=0,
            checkpoint_path=checkpoint,
        )
    assert first_run_queries == ["first query", "second query"]

    resumed_queries: list[str] = []

    async def resume(_db, query: str, *, top_k: int, mode: str):
        resumed_queries.append(query)
        return RetrievalResult(False, "test", "test", [citation("hypertension")], "vector")

    monkeypatch.setattr(evaluation, "search_knowledge", resume)
    report = await run_prototype_evaluation(  # type: ignore[arg-type]
        None,
        dataset,
        mode="vector",
        max_retries=0,
        checkpoint_path=checkpoint,
    )

    assert resumed_queries == ["second query"]
    assert report.case_count == 2
    assert report.recall_at_1 == 1.0


def test_score_case_records_every_candidate_score_and_filter_reason():
    """§4.10：报告必须留下**每个**候选的原始分数与否决原因，否则门槛无法事后复算。"""
    case = EvaluationCase(
        id="case",
        query="测试查询",
        expected_topics=["主题"],
        expected_document_slugs=["expected"],
        safety_class="education",
    )

    result = score_case(
        case,
        [
            citation("other", 0.9, vector=0.31),
            citation("expected", 0.9, vector=0.93),
            citation("keyword-only", 0.9, keyword=1.0),
        ],
        current_consultation_gate(),
    )

    assert [candidate.rank for candidate in result.candidates] == [1, 2, 3]
    assert [candidate.kept for candidate in result.candidates] == [False, True, True]
    assert result.candidates[0].reason == "vector-below-threshold"
    assert result.candidates[0].vector_similarity == 0.31
    assert result.candidates[1].reason == "vector-at-or-above-threshold"
    assert result.candidates[2].reason == "keyword-only-at-or-above-threshold"
    assert result.filtered_count == 1
    assert result.gate_profile == "current-consultation"
    # 过滤后名次重排：原本第二位变成第一位。
    assert result.matched_rank == 1
    assert result.top_similarity == 0.9
    assert result.returned_slugs == ("expected", "keyword-only")


def test_gate_can_filter_out_the_expected_document_and_metrics_follow():
    """§6.3：首项被门槛拦下时，recall@1 与 matched_rank 必须跟着变——说明门槛真的生效了。"""
    case = EvaluationCase(
        id="case",
        query="测试查询",
        expected_topics=["主题"],
        expected_document_slugs=["expected"],
        safety_class="education",
    )
    items = [citation("expected", 0.9, vector=0.3)]

    ungated = score_case(case, items)
    gated = score_case(case, items, current_consultation_gate())

    assert ungated.hit is True
    assert ungated.matched_rank == 1
    assert gated.hit is False
    assert gated.matched_rank is None
    assert gated.top_similarity is None
    assert gated.filtered_count == 1


def test_unsupported_case_passes_only_when_every_candidate_is_filtered():
    """未覆盖问题误召回率归零的机制：全部候选被拦下才算通过。"""
    case = EvaluationCase(
        id="negative",
        query="测试查询",
        expected_topics=[],
        expected_document_slugs=[],
        safety_class="education",
        case_type="unsupported",
    )
    items = [citation("unrelated", 0.9, vector=0.25)]

    ungated = score_case(case, items)
    gated = score_case(case, items, current_consultation_gate())

    assert ungated.false_positive is True
    assert ungated.passed is False
    assert gated.false_positive is False
    assert gated.passed is True
    assert gated.filtered_count == 1


def test_regating_reuses_stored_candidates_without_new_scores():
    """阶段 A 的核心收益：换门槛时只重算判定，原始分数一个字节都不变。"""
    case = EvaluationCase(
        id="case",
        query="测试查询",
        expected_topics=["主题"],
        expected_document_slugs=["expected"],
        safety_class="education",
    )
    stored = score_case(case, [citation("expected", 0.9, vector=0.5)])

    recomputed = regate_case(stored, current_consultation_gate())

    assert [row.vector_similarity for row in recomputed.candidates] == [0.5]
    assert [row.similarity for row in recomputed.candidates] == [0.9]
    assert recomputed.candidates[0].kept is False
    assert recomputed.filtered_count == 1
    assert recomputed.hit is False
    assert stored.hit is True  # 原结果不被就地改写


def test_regating_without_stored_candidates_is_rejected_loudly():
    """旧断点没有逐候选分数时不许假装能算——宁可直接报错。"""
    legacy = EvaluationCaseResult(
        case_id="legacy",
        case_type="supported",
        body_system="respiratory",
        query_style="exact_term",
        safety_class="education",
        split="all",
        hit=True,
        passed=True,
        false_positive=False,
        matched_rank=1,
        top_similarity=0.9,
        returned_slugs=("expected",),
        returned_titles=("expected",),
        returned_trust_levels=("prototype",),
    )

    with pytest.raises(RetrievalEvaluationError, match="逐候选分数"):
        regate_case(legacy, current_consultation_gate())


def _synthetic_report(
    *,
    top_k: int = 3,
    retry_count: int = 0,
    gate: RelevanceGate | None = None,
):
    """三题小报告：一题强证据、一题弱向量、一题未覆盖（用于验证选门槛规则）。"""
    strong = EvaluationCase(
        id="strong",
        query="strong",
        expected_topics=["哮喘"],
        expected_document_slugs=["asthma"],
        safety_class="education",
        split="tune",
    )
    weak = EvaluationCase(
        id="weak",
        query="weak",
        expected_topics=["高血压"],
        expected_document_slugs=["hypertension"],
        safety_class="education",
        split="tune",
    )
    negative = EvaluationCase(
        id="negative",
        query="negative",
        expected_topics=[],
        expected_document_slugs=[],
        safety_class="education",
        case_type="unsupported",
        split="holdout",
    )
    case_results = [
        score_case(strong, [citation("asthma", 0.9, vector=0.95)]),
        score_case(weak, [citation("hypertension", 0.9, vector=0.5)]),
        score_case(negative, [citation("unrelated", 0.9, vector=0.3)]),
    ]
    return build_report(
        case_results,
        mode="hybrid",
        split="all",
        top_k=top_k,
        retry_count=retry_count,
        gate=gate or no_gate(),
    )


def test_results_round_trip_preserves_non_default_settings(tmp_path: Path):
    """真实数据踩过的坑：结果 JSON 是蛇形键，读回时若只认驼峰会静默退回默认值。"""
    results_path = tmp_path / "results.json"
    report = _synthetic_report(top_k=8, retry_count=3, gate=current_consultation_gate())
    results_path.write_text(
        json.dumps({"ok": True, **asdict(report)}, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_results_report(results_path)

    assert loaded.top_k == 8
    assert loaded.retry_count == 3
    assert loaded.gate_profile == "current-consultation"
    assert loaded.gate_thresholds["vector"] == 0.72
    assert loaded.evaluation_split == "all"


def test_select_gate_requires_zero_false_positive_and_keeps_recall():
    """阶段 C 的选参规则：误召回必须先归零；靠牺牲召回换来的零误召回不算通过。"""
    report = _synthetic_report()

    too_tight = candidate_threshold_gate(
        vector_threshold=0.55,
        keyword_threshold=0.5,
        keyword_only_threshold=0.2,
    )
    just_enough = candidate_threshold_gate(
        vector_threshold=0.4,
        keyword_threshold=0.5,
        keyword_only_threshold=0.2,
    )
    more_conservative_tie = candidate_threshold_gate(
        vector_threshold=0.45,
        keyword_threshold=0.5,
        keyword_only_threshold=0.2,
    )

    outcomes = dict(
        (gate.vector_threshold, gated)
        for gate, gated in sweep_gates(report, [too_tight, just_enough, more_conservative_tie])
    )
    assert outcomes[0.55].unsupported_false_positive_rate == 0.0
    assert outcomes[0.55].recall_at_3 == 0.5  # 漏掉弱向量那题 → 不达标
    assert meets_acceptance(outcomes[0.55]) is False
    assert meets_acceptance(outcomes[0.4]) is True

    selected = select_gate(report, [too_tight, just_enough, more_conservative_tie])

    assert selected is not None
    gate, gated = selected
    # 同分时取更保守（阈值更高）的那套。
    assert gate.vector_threshold == 0.45
    assert gated.unsupported_false_positive_rate == 0.0
    assert gated.recall_at_3 == 1.0
    assert gated.pass_rate == 1.0
    assert gated.filtered_count == 1


def test_select_gate_returns_none_when_nothing_meets_the_bar():
    """一条都不达标时必须明确返回 None：调用方据此保持线上行为不变。"""
    report = _synthetic_report()

    assert select_gate(report, [no_gate()]) is None


def test_checkpoint_identity_includes_the_gate():
    """§4.9：门槛进断点身份，否则会把上一套门槛的结果当成这一套的。"""
    dataset = Path(__file__).resolve().parents[1] / "docs" / "medical_retrieval_evaluation_v2.json"

    ungated = _checkpoint_identity(dataset, mode="hybrid", top_k=3, split="all", gate=no_gate())
    gated = _checkpoint_identity(
        dataset,
        mode="hybrid",
        top_k=3,
        split="all",
        gate=current_consultation_gate(),
    )
    regated = _checkpoint_identity(
        dataset,
        mode="hybrid",
        top_k=3,
        split="all",
        gate=current_consultation_gate(),
    )

    assert ungated != gated
    assert gated == regated
    assert gated["gate"]["profile"] == "current-consultation"


async def test_evaluation_with_a_gate_records_it_and_never_reuses_other_gates_checkpoint(
    monkeypatch, tmp_path: Path
):
    """带上门槛跑评测：报告写明门槛，且换门槛后不会命中上一套门槛的断点。"""
    from app.rag import evaluation

    dataset = tmp_path / "evaluation.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "only",
                        "query": "only query",
                        "expected_document_slugs": ["asthma"],
                        "safety_class": "education",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    checkpoint = tmp_path / "checkpoint.json"
    queries: list[str] = []

    async def fake_search(_db, query: str, *, top_k: int, mode: str):
        queries.append(query)
        return RetrievalResult(
            False,
            "test",
            "test",
            [citation("asthma", 0.9, vector=0.3)],
            "hybrid",
        )

    monkeypatch.setattr(evaluation, "search_knowledge", fake_search)

    gated = await run_prototype_evaluation(  # type: ignore[arg-type]
        None,
        dataset,
        mode="hybrid",
        max_retries=0,
        checkpoint_path=checkpoint,
        gate=current_consultation_gate(),
    )
    assert gated.gate_profile == "current-consultation"
    assert gated.gate_thresholds["vector"] == 0.72
    assert gated.filter_reason_counts == {"vector-below-threshold": 1}
    assert gated.filtered_count == 1
    assert gated.hit_count == 0

    # 同一套门槛：命中上一步写下的断点，不再检索。
    resumed = await run_prototype_evaluation(  # type: ignore[arg-type]
        None,
        dataset,
        mode="hybrid",
        max_retries=0,
        checkpoint_path=checkpoint,
        gate=current_consultation_gate(),
    )
    assert queries == ["only query"]
    assert resumed.hit_count == 0

    # 换一套门槛：身份不同，必须**拒绝复用**旧门槛的断点（连检索都不许悄悄发生）。
    with pytest.raises(RetrievalEvaluationError, match="不匹配"):
        await run_prototype_evaluation(  # type: ignore[arg-type]
            None,
            dataset,
            mode="hybrid",
            max_retries=0,
            checkpoint_path=checkpoint,
            gate=no_gate(),
        )
    assert queries == ["only query"]

    # 显式删掉旧断点后重跑：这才允许用新门槛重新检索。
    checkpoint.unlink()
    ungated = await run_prototype_evaluation(  # type: ignore[arg-type]
        None,
        dataset,
        mode="hybrid",
        max_retries=0,
        checkpoint_path=checkpoint,
        gate=no_gate(),
    )
    assert queries == ["only query", "only query"]
    assert ungated.gate_profile == "none"
    assert ungated.hit_count == 1


def _write_results(path: Path) -> None:
    path.write_text(
        json.dumps({"ok": True, **asdict(_synthetic_report())}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_results_file_round_trips_into_an_offline_sweep(tmp_path: Path):
    """结果 JSON 读回后必须能离线换门槛：这正是阶段 C 不重复付费的前提。"""
    results_path = tmp_path / "results.json"
    _write_results(results_path)

    loaded = load_results_report(results_path)

    assert loaded.case_count == 3
    assert [row.vector_similarity for row in loaded.cases[0].candidates] == [0.95]
    assert split_report(loaded, "tune").case_count == 2
    assert split_report(loaded, "holdout").case_count == 1

    args = build_parser().parse_args(
        ["sweep-relevance-gate", str(results_path), "--split", "tune"]
    )
    outcome = run_relevance_gate_sweep(args)

    assert outcome.mode == "sweep"
    assert outcome.gates_evaluated == 7 * 5 * 4
    assert outcome.selected is not None
    assert outcome.sweep["eligibleCount"] >= 1


def test_results_file_without_candidate_scores_is_rejected(tmp_path: Path):
    """没有逐候选分数的旧结果文件不许假装能扫参。"""
    case = EvaluationCase(
        id="legacy",
        query="legacy",
        expected_topics=["哮喘"],
        expected_document_slugs=["asthma"],
        safety_class="education",
    )
    row = asdict(score_case(case, [citation("asthma", 0.9)]))
    row.pop("candidates")
    results_path = tmp_path / "legacy.json"
    results_path.write_text(
        json.dumps({"ok": True, "cases": [row]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(RetrievalEvaluationError, match="逐候选分数"):
        load_results_report(results_path)


def test_holdout_can_only_be_recomputed_after_freezing(tmp_path: Path):
    """结构上保证「选参数只看 tune」：holdout 不带冻结阈值就直接报错。"""
    results_path = tmp_path / "results.json"
    _write_results(results_path)

    peeking = build_parser().parse_args(
        ["sweep-relevance-gate", str(results_path), "--split", "holdout"]
    )
    with pytest.raises(ValueError, match="冻结"):
        run_relevance_gate_sweep(peeking)

    frozen = build_parser().parse_args(
        [
            "sweep-relevance-gate",
            str(results_path),
            "--split",
            "holdout",
            "--frozen-vector-threshold",
            "0.45",
            "--frozen-keyword-threshold",
            "0.5",
        ]
    )
    outcome = run_relevance_gate_sweep(frozen)

    assert outcome.mode == "frozen"
    assert outcome.gates_evaluated == 1
    assert outcome.selected is not None
    assert outcome.selected["thresholds"]["vector"] == 0.45
