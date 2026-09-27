import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.rag.retrieval import RetrievalCitation, RetrievalMode, search_knowledge

DEFAULT_EVALUATION_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "medical_retrieval_evaluation.json"
)
EvaluationSplit = Literal["all", "tune", "holdout"]


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
    top_similarity: float | None
    returned_slugs: tuple[str, ...]
    returned_titles: tuple[str, ...]
    returned_trust_levels: tuple[str, ...]


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
    # 报告必须自带模式：keyword 与 vector 的 similarity 语义不同
    # （pg_trgm word_similarity / 余弦相似度），不写明模式就没法横向对比。
    mode: RetrievalMode = "hybrid"


def load_evaluation_set(path: Path | None = None) -> EvaluationSet:
    try:
        payload = json.loads((path or DEFAULT_EVALUATION_PATH).read_text(encoding="utf-8"))
        return EvaluationSet.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RetrievalEvaluationError("医学检索评测集无效") from exc


def _document_slug(item: RetrievalCitation) -> str:
    return item.canonical_url.rstrip("/").rsplit("/", maxsplit=1)[-1]


def score_case(
    case: EvaluationCase,
    items: list[RetrievalCitation],
) -> EvaluationCaseResult:
    expected_slugs = set(case.expected_document_slugs)
    returned_slugs = tuple(_document_slug(item) for item in items)
    matched_rank = next(
        (
            rank
            for rank, item in enumerate(items, start=1)
            if _document_slug(item) in expected_slugs
        ),
        None,
    )
    unsupported = case.case_type == "unsupported"
    false_positive = unsupported and bool(items)
    hit = not unsupported and matched_rank is not None
    return EvaluationCaseResult(
        case_id=case.id,
        case_type=case.case_type,
        body_system=case.body_system,
        query_style=case.query_style,
        safety_class=case.safety_class,
        split=case.split,
        hit=hit,
        passed=(not false_positive if unsupported else hit),
        false_positive=false_positive,
        matched_rank=matched_rank,
        top_similarity=items[0].similarity if items else None,
        returned_slugs=returned_slugs,
        returned_titles=tuple(item.title for item in items),
        returned_trust_levels=tuple(item.trust_level for item in items),
    )


def _round_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _group_metrics(results: list[EvaluationCaseResult]) -> GroupEvaluationMetrics:
    supported = [result for result in results if result.case_type != "unsupported"]
    unsupported = [result for result in results if result.case_type == "unsupported"]
    reciprocal_ranks = [
        1 / result.matched_rank if result.matched_rank is not None else 0.0
        for result in supported
    ]
    return GroupEvaluationMetrics(
        case_count=len(results),
        supported_case_count=len(supported),
        unsupported_case_count=len(unsupported),
        pass_rate=_round_rate(sum(result.passed for result in results), len(results)),
        recall_at_1=(
            _round_rate(
                sum(result.matched_rank == 1 for result in supported), len(supported)
            )
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
            round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)
            if reciprocal_ranks
            else None
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
) -> RetrievalEvaluationReport:
    if get_settings().app_environment != "development":
        raise RetrievalEvaluationError("原型语料评测只允许在 development 环境运行")
    evaluation_set = load_evaluation_set(path)
    selected_cases = [
        case
        for case in evaluation_set.cases
        if split == "all" or case.split == split
    ]
    if not selected_cases:
        raise RetrievalEvaluationError("医学检索评测集不包含指定分组")
    case_results: list[EvaluationCaseResult] = []
    for case in selected_cases:
        retrieval = await search_knowledge(db, case.query, top_k=top_k, mode=mode)
        case_results.append(score_case(case, retrieval.items))

    supported_results = [
        result for result in case_results if result.case_type != "unsupported"
    ]
    unsupported_results = [
        result for result in case_results if result.case_type == "unsupported"
    ]
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
        result.top_similarity
        for result in case_results
        if result.top_similarity is not None
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
            round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)
            if reciprocal_ranks
            else 0.0
        ),
        unsupported_false_positive_count=false_positive_count,
        unsupported_false_positive_rate=(
            _round_rate(false_positive_count, len(unsupported_results))
            if unsupported_results
            else None
        ),
        pass_rate=_round_rate(
            sum(result.passed for result in case_results), len(case_results)
        ),
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
        mode=mode,
    )
