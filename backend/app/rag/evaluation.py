import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.rag.relevance import (
    RelevanceGate,
    candidate_threshold_gate,
    current_consultation_gate,
    no_gate,
    relevance_decision,
    scores_from_citation,
    scores_from_mapping,
)
from app.rag.retrieval import (
    RetrievalCitation,
    RetrievalError,
    RetrievalMode,
    RetrievalResult,
    search_knowledge,
)

DEFAULT_EVALUATION_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "medical_retrieval_evaluation.json"
)
EvaluationSplit = Literal["all", "tune", "holdout"]
RETRYABLE_EVALUATION_ERRORS = frozenset(
    {"EMBEDDING_TIMEOUT", "EMBEDDING_UNAVAILABLE", "EMBEDDING_RATE_LIMITED"}
)


class RetrievalEvaluationError(ValueError):
    pass


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    query: str = Field(min_length=2)
    expected_topics: list[str] = Field(default_factory=list)
    expected_document_slugs: list[str] = Field(default_factory=list)
    safety_class: str
    case_type: Literal["supported", "confusable", "unsupported"] = "supported"
    body_system: str = "unspecified"
    query_style: str = "unspecified"
    split: Literal["tune", "holdout"] = "tune"

    @model_validator(mode="after")
    def validate_expected_documents(self) -> "EvaluationCase":
        if self.case_type == "unsupported" and self.expected_document_slugs:
            raise ValueError("未覆盖题不应配置期望文档")
        if self.case_type != "unsupported" and not self.expected_document_slugs:
            raise ValueError("已覆盖题至少配置一个期望文档")
        return self


class EvaluationSet(BaseModel):
    model_config = ConfigDict(extra="allow")

    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "EvaluationSet":
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("医学检索评测题 id 必须唯一")
        return self


@dataclass(frozen=True, slots=True)
class EvaluationCandidateScore:
    """**逐候选**分数（阶段 A 的核心）。

    只有首位 `similarity` 的旧报告无法回答「换个门槛会怎样」——那需要重新跑一遍真实检索
    （重复付费），或者退化成离线近似。把每个候选的原始分数与门槛判定一起留下来，
    就能对同一份召回事后复算任意门槛（`regate_case`），tune 集扫参不再花第二次钱。
    """

    rank: int
    slug: str
    title: str
    source_key: str
    trust_level: str
    similarity: float
    keyword_score: float | None
    vector_similarity: float | None
    rerank_score: float | None
    kept: bool
    reason: str


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    case_id: str
    case_type: str
    body_system: str
    query_style: str
    safety_class: str
    split: str
    hit: bool
    passed: bool
    false_positive: bool
    matched_rank: int | None
    # 首个**通过门槛**候选的 similarity；门槛关闭时与旧报告的「首位相似度」完全一致。
    top_similarity: float | None
    returned_slugs: tuple[str, ...]
    returned_titles: tuple[str, ...]
    returned_trust_levels: tuple[str, ...]
    # 期望文档 slug 必须进报告：事后换门槛重算命中与否要用它（见 `regate_case`）。
    expected_slugs: tuple[str, ...] = ()
    candidates: tuple[EvaluationCandidateScore, ...] = ()
    filtered_count: int = 0
    gate_profile: str = "none"


@dataclass(frozen=True, slots=True)
class GroupEvaluationMetrics:
    case_count: int
    supported_case_count: int
    unsupported_case_count: int
    pass_rate: float
    recall_at_1: float | None
    recall_at_3: float | None
    mean_reciprocal_rank: float | None
    unsupported_false_positive_rate: float | None


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationReport:
    metric: str
    case_count: int
    supported_case_count: int
    unsupported_case_count: int
    hit_count: int
    topic_hit_rate: float
    recall_at_1: float
    recall_at_3: float
    mean_reciprocal_rank: float
    unsupported_false_positive_count: int
    unsupported_false_positive_rate: float | None
    pass_rate: float
    mean_top_similarity: float | None
    top_k: int
    cases: tuple[EvaluationCaseResult, ...]
    by_body_system: dict[str, GroupEvaluationMetrics]
    by_query_style: dict[str, GroupEvaluationMetrics]
    by_safety_class: dict[str, GroupEvaluationMetrics]
    by_split: dict[str, GroupEvaluationMetrics]
    evaluation_split: EvaluationSplit = "all"
    retry_count: int = 0
    # 报告必须自带模式：keyword 与 vector 的 similarity 语义不同
    # （pg_trgm word_similarity / 余弦相似度），不写明模式就没法横向对比。
    mode: RetrievalMode = "hybrid"
    # 报告也必须自带门槛：同一份召回在不同门槛下指标不同，不写清门槛数字，指标无法复核。
    gate_profile: str = "none"
    gate_thresholds: dict[str, float | None] = field(default_factory=dict)
    filtered_count: int = 0
    filter_reason_counts: dict[str, int] = field(default_factory=dict)


async def _search_with_retry(
    db: AsyncSession,
    case: EvaluationCase,
    *,
    top_k: int,
    mode: RetrievalMode,
    max_retries: int,
) -> tuple[RetrievalResult, int]:
    retry_count = 0
    while True:
        try:
            result = await search_knowledge(db, case.query, top_k=top_k, mode=mode)
            return result, retry_count
        except RetrievalError as exc:
            if exc.code not in RETRYABLE_EVALUATION_ERRORS or retry_count >= max_retries:
                raise RetrievalEvaluationError(f"评测题 {case.id} 检索失败（{exc.code}）") from exc
            retry_count += 1
            await asyncio.sleep(min(2 ** (retry_count - 1), 4))


def load_evaluation_set(path: Path | None = None) -> EvaluationSet:
    try:
        payload = json.loads((path or DEFAULT_EVALUATION_PATH).read_text(encoding="utf-8"))
        return EvaluationSet.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RetrievalEvaluationError("医学检索评测集无效") from exc


def _checkpoint_identity(
    dataset_path: Path,
    *,
    mode: RetrievalMode,
    top_k: int,
    split: EvaluationSplit,
    gate: RelevanceGate,
) -> dict[str, object]:
    try:
        dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RetrievalEvaluationError("无法读取医学检索评测集") from exc
    return {
        "schemaVersion": 2,
        "datasetSha256": dataset_sha256,
        "mode": mode,
        "topK": top_k,
        "split": split,
        # 门槛与全部阈值都进身份：换了 profile 或任何一个数字，旧断点必须被拒绝复用，
        # 否则会把「上一套门槛下的结果」当成「这一套门槛下的结果」写进报告。
        "gate": gate.identity(),
    }


def case_result_from_row(row: Mapping[str, object]) -> EvaluationCaseResult:
    """把 JSON 里的一行还原成结果对象：断点与结果文件共用同一套还原逻辑。"""
    raw_candidates = row.get("candidates") or []
    return EvaluationCaseResult(
        **{
            **row,
            "returned_slugs": tuple(row["returned_slugs"]),  # type: ignore[arg-type]
            "returned_titles": tuple(row["returned_titles"]),  # type: ignore[arg-type]
            "returned_trust_levels": tuple(row["returned_trust_levels"]),  # type: ignore[arg-type]
            "expected_slugs": tuple(row.get("expected_slugs") or ()),  # type: ignore[arg-type]
            "candidates": tuple(
                EvaluationCandidateScore(**candidate)  # type: ignore[arg-type]
                for candidate in raw_candidates  # type: ignore[union-attr]
            ),
        }
    )


def _load_checkpoint(
    path: Path,
    identity: dict[str, object],
) -> tuple[dict[str, EvaluationCaseResult], int]:
    if not path.exists():
        return {}, 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("identity") != identity:
            raise ValueError("checkpoint identity mismatch")
        rows = payload.get("cases")
        if not isinstance(rows, dict):
            raise ValueError("checkpoint cases missing")
        results = {case_id: case_result_from_row(row) for case_id, row in rows.items()}
        retry_count = payload.get("retryCount", 0)
        if not isinstance(retry_count, int) or retry_count < 0:
            raise ValueError("checkpoint retry count invalid")
        return results, retry_count
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise RetrievalEvaluationError("医学检索评测断点无效或与本次参数不匹配") from exc


def _write_checkpoint(
    path: Path,
    identity: dict[str, object],
    results: dict[str, EvaluationCaseResult],
    retry_count: int,
) -> None:
    payload = {
        "identity": identity,
        "retryCount": retry_count,
        "cases": {case_id: asdict(result) for case_id, result in results.items()},
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise RetrievalEvaluationError("无法写入医学检索评测断点") from exc


def _document_slug(item: RetrievalCitation) -> str:
    return item.canonical_url.rstrip("/").rsplit("/", maxsplit=1)[-1]


def candidate_scores(
    items: list[RetrievalCitation],
    gate: RelevanceGate,
) -> tuple[EvaluationCandidateScore, ...]:
    """把一次召回的**每个**候选连同门槛判定一起记下来（不是只记首位）。"""
    rows = []
    for rank, item in enumerate(items, start=1):
        decision = relevance_decision(scores_from_citation(item), gate)
        rows.append(
            EvaluationCandidateScore(
                rank=rank,
                slug=_document_slug(item),
                title=item.title,
                source_key=item.source_key,
                trust_level=item.trust_level,
                similarity=item.similarity,
                keyword_score=item.keyword_score,
                vector_similarity=item.vector_similarity,
                rerank_score=item.rerank_score,
                kept=decision.keep,
                reason=decision.reason,
            )
        )
    return tuple(rows)


def evaluate_candidates(
    *,
    case_id: str,
    case_type: str,
    body_system: str,
    query_style: str,
    safety_class: str,
    split: str,
    expected_slugs: tuple[str, ...],
    candidates: tuple[EvaluationCandidateScore, ...],
    gate_profile: str,
) -> EvaluationCaseResult:
    """按逐候选的 `kept` 算指标。`score_case` 与事后重算 `regate_case` 共用这一份逻辑。"""
    expected = set(expected_slugs)
    kept = [candidate for candidate in candidates if candidate.kept]
    matched_rank = next(
        (
            rank
            for rank, candidate in enumerate(kept, start=1)
            if candidate.slug in expected
        ),
        None,
    )
    unsupported = case_type == "unsupported"
    false_positive = unsupported and bool(kept)
    hit = not unsupported and matched_rank is not None
    return EvaluationCaseResult(
        case_id=case_id,
        case_type=case_type,
        body_system=body_system,
        query_style=query_style,
        safety_class=safety_class,
        split=split,
        hit=hit,
        passed=(not false_positive if unsupported else hit),
        false_positive=false_positive,
        matched_rank=matched_rank,
        top_similarity=kept[0].similarity if kept else None,
        returned_slugs=tuple(candidate.slug for candidate in kept),
        returned_titles=tuple(candidate.title for candidate in kept),
        returned_trust_levels=tuple(candidate.trust_level for candidate in kept),
        expected_slugs=expected_slugs,
        candidates=candidates,
        filtered_count=len(candidates) - len(kept),
        gate_profile=gate_profile,
    )


def score_case(
    case: EvaluationCase,
    items: list[RetrievalCitation],
    gate: RelevanceGate | None = None,
) -> EvaluationCaseResult:
    """给一道题打分。省略 `gate` 时不过滤——那正是本任务之前的行为，必须逐位保持不变。"""
    active_gate = gate or no_gate()
    return evaluate_candidates(
        case_id=case.id,
        case_type=case.case_type,
        body_system=case.body_system,
        query_style=case.query_style,
        safety_class=case.safety_class,
        split=case.split,
        expected_slugs=tuple(case.expected_document_slugs),
        candidates=candidate_scores(items, active_gate),
        gate_profile=active_gate.profile,
    )


def regate_case(
    result: EvaluationCaseResult,
    gate: RelevanceGate,
) -> EvaluationCaseResult:
    """用**已保存的逐候选分数**换一套门槛重算结果——不调用检索、不重复付费。

    这正是阶段 A 要留下逐候选分数的理由：tune 集扫参必须在本地完成，不能每换一个阈值
    就把 80 道题重跑一遍真实向量接口。旧断点没有候选记录时直接报错，不假装能算。
    """
    if not result.candidates:
        raise RetrievalEvaluationError("该题结果没有逐候选分数，无法换门槛重算")
    regated = tuple(
        replace(candidate, kept=decision.keep, reason=decision.reason)
        for candidate in result.candidates
        for decision in (relevance_decision(scores_from_mapping(asdict(candidate)), gate),)
    )
    return evaluate_candidates(
        case_id=result.case_id,
        case_type=result.case_type,
        body_system=result.body_system,
        query_style=result.query_style,
        safety_class=result.safety_class,
        split=result.split,
        expected_slugs=result.expected_slugs,
        candidates=regated,
        gate_profile=gate.profile,
    )


def _round_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _group_metrics(results: list[EvaluationCaseResult]) -> GroupEvaluationMetrics:
    supported = [result for result in results if result.case_type != "unsupported"]
    unsupported = [result for result in results if result.case_type == "unsupported"]
    reciprocal_ranks = [
        1 / result.matched_rank if result.matched_rank is not None else 0.0 for result in supported
    ]
    return GroupEvaluationMetrics(
        case_count=len(results),
        supported_case_count=len(supported),
        unsupported_case_count=len(unsupported),
        pass_rate=_round_rate(sum(result.passed for result in results), len(results)),
        recall_at_1=(
            _round_rate(sum(result.matched_rank == 1 for result in supported), len(supported))
            if supported
            else None
        ),
        recall_at_3=(
            _round_rate(
                sum(
                    result.matched_rank is not None and result.matched_rank <= 3
                    for result in supported
                ),
                len(supported),
            )
            if supported
            else None
        ),
        mean_reciprocal_rank=(
            round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4) if reciprocal_ranks else None
        ),
        unsupported_false_positive_rate=(
            _round_rate(sum(result.false_positive for result in unsupported), len(unsupported))
            if unsupported
            else None
        ),
    )


def _group_by(
    results: list[EvaluationCaseResult], attribute: str
) -> dict[str, GroupEvaluationMetrics]:
    grouped: dict[str, list[EvaluationCaseResult]] = {}
    for result in results:
        grouped.setdefault(str(getattr(result, attribute)), []).append(result)
    return {key: _group_metrics(grouped[key]) for key in sorted(grouped)}


async def run_prototype_evaluation(
    db: AsyncSession,
    path: Path | None = None,
    *,
    top_k: int = 3,
    mode: RetrievalMode = "hybrid",
    split: EvaluationSplit = "all",
    max_retries: int = 2,
    checkpoint_path: Path | None = None,
    gate: RelevanceGate | None = None,
) -> RetrievalEvaluationReport:
    if get_settings().app_environment != "development":
        raise RetrievalEvaluationError("原型语料评测只允许在 development 环境运行")
    if not 0 <= max_retries <= 5:
        raise RetrievalEvaluationError("单题重试次数必须为 0-5")
    active_gate = gate or no_gate()
    dataset_path = path or DEFAULT_EVALUATION_PATH
    evaluation_set = load_evaluation_set(dataset_path)
    selected_cases = [
        case for case in evaluation_set.cases if split == "all" or case.split == split
    ]
    if not selected_cases:
        raise RetrievalEvaluationError("医学检索评测集不包含指定分组")
    checkpoint_identity = _checkpoint_identity(
        dataset_path,
        mode=mode,
        top_k=top_k,
        split=split,
        gate=active_gate,
    )
    checkpoint_results, retry_count = (
        _load_checkpoint(checkpoint_path, checkpoint_identity)
        if checkpoint_path is not None
        else ({}, 0)
    )
    selected_ids = {case.id for case in selected_cases}
    if not set(checkpoint_results) <= selected_ids:
        raise RetrievalEvaluationError("医学检索评测断点包含本次题集之外的题目")
    case_results: list[EvaluationCaseResult] = []
    for case in selected_cases:
        cached = checkpoint_results.get(case.id)
        if cached is not None:
            case_results.append(cached)
            continue
        retrieval, case_retries = await _search_with_retry(
            db,
            case,
            top_k=top_k,
            mode=mode,
            max_retries=max_retries,
        )
        retry_count += case_retries
        result = score_case(case, retrieval.items, active_gate)
        case_results.append(result)
        checkpoint_results[case.id] = result
        if checkpoint_path is not None:
            _write_checkpoint(
                checkpoint_path,
                checkpoint_identity,
                checkpoint_results,
                retry_count,
            )

    return build_report(
        case_results,
        mode=mode,
        split=split,
        top_k=top_k,
        retry_count=retry_count,
        gate=active_gate,
    )


def _filter_reason_counts(
    case_results: list[EvaluationCaseResult],
) -> dict[str, int]:
    """被过滤候选按 reason 计数：只给总体百分比，无法回答「为什么被丢掉」。"""
    counts: dict[str, int] = {}
    for result in case_results:
        for candidate in result.candidates:
            if candidate.kept:
                continue
            counts[candidate.reason] = counts.get(candidate.reason, 0) + 1
    return dict(sorted(counts.items()))


def build_report(
    case_results: list[EvaluationCaseResult],
    *,
    mode: RetrievalMode,
    split: EvaluationSplit,
    top_k: int,
    retry_count: int,
    gate: RelevanceGate,
) -> RetrievalEvaluationReport:
    """把逐题结果汇总成报告。

    抽成公共函数是为了让「换门槛离线重算」（`regate_case`）复用**同一份**指标口径——
    否则扫参的结果与正式跑出来的结果可能因为两套算法而不可比。
    """
    supported_results = [result for result in case_results if result.case_type != "unsupported"]
    unsupported_results = [result for result in case_results if result.case_type == "unsupported"]
    hit_count = sum(result.hit for result in supported_results)
    recall_at_1 = _round_rate(
        sum(result.matched_rank == 1 for result in supported_results),
        len(supported_results),
    )
    recall_at_3 = _round_rate(
        sum(
            result.matched_rank is not None and result.matched_rank <= 3
            for result in supported_results
        ),
        len(supported_results),
    )
    reciprocal_ranks = [
        1 / result.matched_rank if result.matched_rank is not None else 0.0
        for result in supported_results
    ]
    false_positive_count = sum(result.false_positive for result in unsupported_results)
    similarities = [
        result.top_similarity for result in case_results if result.top_similarity is not None
    ]
    return RetrievalEvaluationReport(
        metric="prototype_document_retrieval",
        case_count=len(case_results),
        supported_case_count=len(supported_results),
        unsupported_case_count=len(unsupported_results),
        hit_count=hit_count,
        topic_hit_rate=_round_rate(hit_count, len(supported_results)),
        recall_at_1=recall_at_1,
        recall_at_3=recall_at_3,
        mean_reciprocal_rank=(
            round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4) if reciprocal_ranks else 0.0
        ),
        unsupported_false_positive_count=false_positive_count,
        unsupported_false_positive_rate=(
            _round_rate(false_positive_count, len(unsupported_results))
            if unsupported_results
            else None
        ),
        pass_rate=_round_rate(sum(result.passed for result in case_results), len(case_results)),
        mean_top_similarity=(
            round(sum(similarities) / len(similarities), 6) if similarities else None
        ),
        top_k=top_k,
        cases=tuple(case_results),
        by_body_system=_group_by(case_results, "body_system"),
        by_query_style=_group_by(case_results, "query_style"),
        by_safety_class=_group_by(case_results, "safety_class"),
        by_split=_group_by(case_results, "split"),
        evaluation_split=split,
        retry_count=retry_count,
        mode=mode,
        gate_profile=gate.profile,
        gate_thresholds=gate.thresholds(),
        filtered_count=sum(result.filtered_count for result in case_results),
        filter_reason_counts=_filter_reason_counts(case_results),
    )


def gate_from_report(report: RetrievalEvaluationReport) -> RelevanceGate:
    """报告里存的是 profile + 阈值快照（可 JSON 化），这里还原成可用的 gate 对象。"""
    thresholds = report.gate_thresholds
    return RelevanceGate(
        profile=report.gate_profile,  # type: ignore[arg-type]
        vector_threshold=thresholds.get("vector"),
        keyword_threshold=thresholds.get("keyword"),
        keyword_only_threshold=thresholds.get("keywordOnly"),
        web_vector_threshold=thresholds.get("webVector"),
    )


def _report_field(
    payload: Mapping[str, object],
    *keys: str,
    default: object = None,
) -> object:
    """结果 JSON 由 `asdict` 写出，键名是**蛇形**；同时容忍驼峰，避免静默退回默认值。

    真实数据踩过这个坑：早先只读驼峰键，于是 `retry_count`、`top_k` 等被悄悄换成默认值，
    而默认值恰好与原值相同（都是 hybrid/3），表面完全看不出问题。
    """
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def load_results_report(path: Path) -> RetrievalEvaluationReport:
    """读回 `evaluate-prototype` 写出的结果 JSON，重建报告（逐候选分数一并还原）。

    这是阶段 C「只在 tune 上选参数」的工具入口：同一份**真实**召回结果可以被反复换门槛
    离线重算，不需要为了扫参再打一次向量接口。缺逐候选分数的旧结果文件会明确报错，
    而不是给出一份看起来能用的空扫参。
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["cases"]
        if not isinstance(rows, list):
            raise TypeError("cases must be a list")
        case_results = [case_result_from_row(row) for row in rows]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RetrievalEvaluationError("医学检索评测结果文件无法读取或格式不符") from exc
    if not case_results:
        raise RetrievalEvaluationError("医学检索评测结果文件没有题目")
    if not any(result.candidates for result in case_results):
        raise RetrievalEvaluationError("该结果文件没有逐候选分数，无法离线换门槛")
    thresholds = _report_field(payload, "gate_thresholds", "gateThresholds", default={}) or {}
    gate = RelevanceGate(
        profile=_report_field(payload, "gate_profile", "gateProfile", default="none"),  # type: ignore[arg-type]
        vector_threshold=thresholds.get("vector"),  # type: ignore[union-attr]
        keyword_threshold=thresholds.get("keyword"),  # type: ignore[union-attr]
        keyword_only_threshold=thresholds.get("keywordOnly"),  # type: ignore[union-attr]
        web_vector_threshold=thresholds.get("webVector"),  # type: ignore[union-attr]
    )
    return build_report(
        case_results,
        mode=_report_field(payload, "mode", default="hybrid"),  # type: ignore[arg-type]
        split=_report_field(  # type: ignore[arg-type]
            payload, "evaluation_split", "evaluationSplit", default="all"
        ),
        top_k=_report_field(payload, "top_k", "topK", default=3),  # type: ignore[arg-type]
        retry_count=_report_field(  # type: ignore[arg-type]
            payload, "retry_count", "retryCount", default=0
        ),
        gate=gate,
    )


def split_report(
    report: RetrievalEvaluationReport,
    split: EvaluationSplit,
) -> RetrievalEvaluationReport:
    """按 split 切出子报告。**选参数只看 tune**，holdout 只在冻结后看一次。"""
    cases = [case for case in report.cases if split == "all" or case.split == split]
    if not cases:
        raise RetrievalEvaluationError(f"结果里没有 {split} 的题目")
    return build_report(
        cases,
        mode=report.mode,
        split=split,
        top_k=report.top_k,
        retry_count=report.retry_count,
        gate=gate_from_report(report),
    )


def threshold_grid(
    *,
    vector_thresholds: Sequence[float],
    keyword_thresholds: Sequence[float],
    keyword_only_thresholds: Sequence[float],
) -> list[RelevanceGate]:
    """候选门槛网格。列表由调用方显式给出，保证扫参可复核、可重跑。"""
    return [
        candidate_threshold_gate(
            vector_threshold=vector,
            keyword_threshold=keyword,
            keyword_only_threshold=keyword_only,
        )
        for vector in vector_thresholds
        for keyword in keyword_thresholds
        for keyword_only in keyword_only_thresholds
    ]


def _sweep_row(
    gate: RelevanceGate,
    gated: RetrievalEvaluationReport,
) -> dict[str, object]:
    return {
        "profile": gate.profile,
        "thresholds": gate.thresholds(),
        "unsupportedFalsePositiveCount": gated.unsupported_false_positive_count,
        "unsupportedFalsePositiveRate": gated.unsupported_false_positive_rate,
        "recallAt1": gated.recall_at_1,
        "recallAt3": gated.recall_at_3,
        "passRate": gated.pass_rate,
        "hitCount": gated.hit_count,
        "filteredCount": gated.filtered_count,
        "filterReasonCounts": gated.filter_reason_counts,
        "eligible": meets_acceptance(gated),
    }


def sweep_report(
    report: RetrievalEvaluationReport,
    gates: Sequence[RelevanceGate],
) -> dict[str, object]:
    """扫参结果（机器可读）：全部候选 + 达标者 + 按规则选中的那一套。"""
    outcomes = sweep_gates(report, gates)
    rows = [_sweep_row(gate, gated) for gate, gated in outcomes]
    eligible = [row for row in rows if row["eligible"]]
    selected = select_gate(report, gates)
    return {
        "caseCount": report.case_count,
        "supportedCaseCount": report.supported_case_count,
        "unsupportedCaseCount": report.unsupported_case_count,
        "evaluationSplit": report.evaluation_split,
        "gates": rows,
        "eligibleCount": len(eligible),
        "eligible": eligible,
        "selected": _sweep_row(*selected) if selected else None,
        "acceptance": {
            "maxUnsupportedFalsePositiveRate": GATE_ACCEPTANCE_MAX_FALSE_POSITIVE_RATE,
            "minRecallAt3": GATE_ACCEPTANCE_MIN_RECALL_AT_3,
            "minPassRate": GATE_ACCEPTANCE_MIN_PASS_RATE,
        },
    }


def current_consultation_report(
    report: RetrievalEvaluationReport,
) -> RetrievalEvaluationReport:
    """把同一份召回按**现有咨询门槛**重算，用于回答「统一前后差多少」。"""
    return build_report(
        [regate_case(case, current_consultation_gate()) for case in report.cases],
        mode=report.mode,
        split=report.evaluation_split,
        top_k=report.top_k,
        retry_count=report.retry_count,
        gate=current_consultation_gate(),
    )
GATE_ACCEPTANCE_MAX_FALSE_POSITIVE_RATE = 0.0
GATE_ACCEPTANCE_MIN_RECALL_AT_3 = 0.90
GATE_ACCEPTANCE_MIN_PASS_RATE = 0.90


def meets_acceptance(report: RetrievalEvaluationReport) -> bool:
    """三条硬指标是否同时满足：未覆盖误召回率 0、Recall@3 ≥ 0.90、总体通过率 ≥ 0.90。"""
    return (
        (report.unsupported_false_positive_rate or 0.0) <= GATE_ACCEPTANCE_MAX_FALSE_POSITIVE_RATE
        and report.recall_at_3 >= GATE_ACCEPTANCE_MIN_RECALL_AT_3
        and report.pass_rate >= GATE_ACCEPTANCE_MIN_PASS_RATE
    )


def sweep_gates(
    report: RetrievalEvaluationReport,
    gates: Sequence[RelevanceGate],
) -> list[tuple[RelevanceGate, RetrievalEvaluationReport]]:
    """在**已保存的逐候选分数**上离线评估多套门槛：不调用检索、不重复付费。

    这是阶段 A 的直接用途：tune 集扫参必须能在一份真实召回结果上反复重算，
    否则每换一个阈值就要重跑 60 道题的向量接口。
    """
    outcomes = []
    for gate in gates:
        regated = [regate_case(case, gate) for case in report.cases]
        outcomes.append(
            (
                gate,
                build_report(
                    regated,
                    mode=report.mode,
                    split=report.evaluation_split,
                    top_k=report.top_k,
                    retry_count=report.retry_count,
                    gate=gate,
                ),
            )
        )
    return outcomes


def select_gate(
    report: RetrievalEvaluationReport,
    gates: Sequence[RelevanceGate],
) -> tuple[RelevanceGate, RetrievalEvaluationReport] | None:
    """按计划阶段 C 的规则选门槛：**先要求未覆盖误召回率为 0**，再最大化总体通过率。

    Recall@3 低于 0.90 的候选直接淘汰（漏召回不能靠放宽门槛换通过率）。
    同分时选阈值**更高**的那套——更保守的一侧在面对新题时更不容易误召回，
    这也是「宁可少给证据，不拿最像但无关的资料充当医学证据」的产品要求。
    都不满足时返回 `None`：那就保持线上行为不变并报告，不许回头再调参。
    """
    eligible = [
        (gate, gated)
        for gate, gated in sweep_gates(report, gates)
        if (gated.unsupported_false_positive_rate or 0.0) <= GATE_ACCEPTANCE_MAX_FALSE_POSITIVE_RATE
        and gated.recall_at_3 >= GATE_ACCEPTANCE_MIN_RECALL_AT_3
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item[1].pass_rate,
            item[1].recall_at_3,
            item[0].vector_threshold or 0.0,
            item[0].keyword_only_threshold or 0.0,
        ),
    )
