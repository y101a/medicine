import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.rag.retrieval import RetrievalCitation, RetrievalMode, search_knowledge

DEFAULT_EVALUATION_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "medical_retrieval_evaluation.json"
)


class RetrievalEvaluationError(ValueError):
    pass


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    query: str = Field(min_length=2)
    expected_topics: list[str] = Field(min_length=1)
    expected_document_slugs: list[str] = Field(min_length=1)
    safety_class: str


class EvaluationSet(BaseModel):
    model_config = ConfigDict(extra="allow")

    cases: list[EvaluationCase] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    case_id: str
    hit: bool
    matched_rank: int | None
    top_similarity: float | None
    returned_titles: tuple[str, ...]
    returned_trust_levels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationReport:
    metric: str
    case_count: int
    hit_count: int
    topic_hit_rate: float
    mean_top_similarity: float | None
    top_k: int
    cases: tuple[EvaluationCaseResult, ...]
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
    matched_rank = next(
        (
            rank
            for rank, item in enumerate(items, start=1)
            if _document_slug(item) in expected_slugs
        ),
        None,
    )
    return EvaluationCaseResult(
        case_id=case.id,
        hit=matched_rank is not None,
        matched_rank=matched_rank,
        top_similarity=items[0].similarity if items else None,
        returned_titles=tuple(item.title for item in items),
        returned_trust_levels=tuple(item.trust_level for item in items),
    )


async def run_prototype_evaluation(
    db: AsyncSession,
    path: Path | None = None,
    *,
    top_k: int = 3,
    mode: RetrievalMode = "hybrid",
) -> RetrievalEvaluationReport:
    if get_settings().app_environment != "development":
        raise RetrievalEvaluationError("原型语料评测只允许在 development 环境运行")
    evaluation_set = load_evaluation_set(path)
    case_results: list[EvaluationCaseResult] = []
    for case in evaluation_set.cases:
        retrieval = await search_knowledge(db, case.query, top_k=top_k, mode=mode)
        case_results.append(score_case(case, retrieval.items))

    hit_count = sum(result.hit for result in case_results)
    similarities = [
        result.top_similarity
        for result in case_results
        if result.top_similarity is not None
    ]
    return RetrievalEvaluationReport(
        metric="prototype_document_hit_at_k",
        case_count=len(case_results),
        hit_count=hit_count,
        topic_hit_rate=round(hit_count / len(case_results), 4),
        mean_top_similarity=(
            round(sum(similarities) / len(similarities), 6) if similarities else None
        ),
        top_k=top_k,
        cases=tuple(case_results),
        mode=mode,
    )
