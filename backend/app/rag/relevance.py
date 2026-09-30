"""检索相关度门槛：全项目唯一一份「这个候选还算不算医学证据」的判定。

**为什么需要它**：咨询图 ``app/ai/graph/workflow.py`` 早就有局部门槛——普通来源向量
0.72、网页来源 0.60、关键词分 ≥0.2 也放行——但那份数字长在 workflow 内部；评测器
(``app/rag/evaluation.py``)、知识接口 (``app/api/routes/knowledge.py``)、文档生成
(``app/services/document_generations.py``) 曾经没有统一使用它。同一次召回因此在三条链路里
行为不同，而 0.55 那种「只用首位分数」的离线近似又不是逐候选实验，不能直接上线。
2026-09-30 修订 `medicine-use` 后重新运行冻结 80 题，逐候选门槛通过 tune/holdout 验收，
三条消费者现统一调用本模块的 ``production_relevance_gate``。

本模块只做一件事：给定**一个候选的真实分数**与一个 gate，回答保留还是丢弃，并给出
可测试的 reason。纯函数、无 IO、不碰数据库、不调用模型。

**分数语义纪律**（写测试时也按这几条，见 `RETRIEVAL_RELEVANCE_GATE_PLAN.md` 阶段 B）：

1. 有 ``vector_similarity`` 时，向量门槛**只与向量分比较**；``rerank_score`` 是融合排序分，
   **永远不能**冒充余弦相似度去放行候选。
2. 没有当前向量、但关键词命中的候选走**单独的关键词规则**
   （``keyword_only_threshold``），不许因为缺向量就被误杀——这是既有
   「混合检索的无向量精确命中」回归测试保护的行为。
3. 有向量但向量分不足时，允许用关键词分作补充证据（``keyword_threshold``）。两种关键词
   阈值分开配置，正是为了避免「普通弱关键词用 0.2 的宽松规则误放无关文档」。
4. legacy/mock 证据只有 ``similarity``（评测桩、联网摘要）时走兼容路径：用 ``similarity``
   与向量门槛比较，并明确记为 legacy reason，便于在报告里把兼容路径与真实向量证据分开看。

**profile**：

- ``none``：不过滤。用于让评测结果与原始召回对齐（``none`` 是评测基线，不是线上取值）。
- ``current-consultation``：**精确复刻** ``workflow.py`` 的历史行为
  （向量 0.72、网页来源 0.60、关键词 0.2）。
- ``candidate-threshold``：待调参数。只允许在 tune 集上选择、并经 holdout 一次性验证通过后，
  才可作为线上默认（见计划阶段 C/D）。
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.rag.retrieval import RetrievalCitation
from app.rag.web_search import SOURCE_KEY as WEB_SEARCH_SOURCE_KEY

RelevanceGateProfile = Literal["none", "current-consultation", "candidate-threshold"]
RELEVANCE_GATE_PROFILES: tuple[RelevanceGateProfile, ...] = (
    "none",
    "current-consultation",
    "candidate-threshold",
)

# 咨询链路历史取值（2026-09 之前就写死在 workflow.py 里）。改这里的数字等于改线上行为，
# 必须按计划阶段 C 用 tune 选择、holdout 验证后才允许动。
CURRENT_CONSULTATION_VECTOR_THRESHOLD = 0.72
CURRENT_CONSULTATION_WEB_VECTOR_THRESHOLD = 0.60
CURRENT_CONSULTATION_KEYWORD_THRESHOLD = 0.2
CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD = 0.2

# 联网搜索缓存的语料是另一种来源（界面上标「未经医学审核」），历史门槛更宽；本任务不改它的
# 触发与来源标注，只把数字集中到这里，避免再出现第二份。
WEB_SEARCH_VECTOR_THRESHOLD = CURRENT_CONSULTATION_WEB_VECTOR_THRESHOLD

# 生产候选门槛来自 2026-09-30 冻结评测：只用 tune 选择，holdout 仅验证一次。
# holdout：未覆盖误召回率 0、Recall@3 0.9375、总体通过率 0.95。
# 无向量关键词 0.2 是保护精确术语命中的产品约束，不是扫参维度。
PRODUCTION_VECTOR_THRESHOLD = 0.56
PRODUCTION_KEYWORD_THRESHOLD = 0.2
PRODUCTION_KEYWORD_ONLY_THRESHOLD = 0.2

RelevanceReason = Literal[
    "profile-none",
    "vector-at-or-above-threshold",
    "keyword-at-or-above-threshold",
    "keyword-only-at-or-above-threshold",
    "vector-below-threshold",
    "keyword-only-below-threshold",
    "legacy-similarity-at-or-above-threshold",
    "legacy-similarity-below-threshold",
]

@dataclass(frozen=True, slots=True)
class RelevanceScores:
    """一个候选的分数。只承载**真实存在**的分数，不做任何推算或回填。"""

    similarity: float
    keyword_score: float | None = None
    vector_similarity: float | None = None
    rerank_score: float | None = None
    source_key: str = ""


@dataclass(frozen=True, slots=True)
class RelevanceGate:
    profile: RelevanceGateProfile
    vector_threshold: float | None
    keyword_threshold: float | None
    keyword_only_threshold: float | None
    web_vector_threshold: float | None = None

    def thresholds(self) -> dict[str, float | None]:
        """断点/报告用的完整阈值快照：门槛一变就不允许复用旧断点。"""
        return {
            "vector": self.vector_threshold,
            "keyword": self.keyword_threshold,
            "keywordOnly": self.keyword_only_threshold,
            "webVector": self.web_vector_threshold,
        }

    def identity(self) -> dict[str, object]:
        return {"profile": self.profile, **self.thresholds()}

    def describe(self) -> str:
        if self.profile == "none":
            return "none（不过滤）"
        parts = [f"向量≥{self.vector_threshold}", f"关键词≥{self.keyword_threshold}"]
        if self.keyword_only_threshold is not None:
            parts.append(f"无向量关键词≥{self.keyword_only_threshold}")
        if self.web_vector_threshold is not None:
            parts.append(f"网页来源≥{self.web_vector_threshold}")
        return f"{self.profile}（" + "，".join(parts) + "）"


@dataclass(frozen=True, slots=True)
class RelevanceDecision:
    keep: bool
    reason: RelevanceReason


def no_gate() -> RelevanceGate:
    """不过滤：评测 `none` 基线与「线上维持原样」时使用。"""
    return RelevanceGate("none", None, None, None, None)


def current_consultation_gate(
    *,
    web_vector_threshold: float | None = WEB_SEARCH_VECTOR_THRESHOLD,
) -> RelevanceGate:
    """精确复刻咨询链路历史门槛（向量 0.72 / 网页来源 0.60 / 关键词 0.2）。

    `web_vector_threshold` 之所以还能单独指定：咨询图里有两个历史分支——命中泛化主题时
    按来源区分（网页缓存语料 0.60），未命中泛化主题时此前对**所有**来源一律 0.72。
    保留这个参数是为了在抽取公共门槛时做到行为逐位不变；数字仍只有本模块一份。
    """
    return RelevanceGate(
        "current-consultation",
        CURRENT_CONSULTATION_VECTOR_THRESHOLD,
        CURRENT_CONSULTATION_KEYWORD_THRESHOLD,
        CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD,
        web_vector_threshold,
    )


def candidate_threshold_gate(
    *,
    vector_threshold: float,
    keyword_threshold: float,
    keyword_only_threshold: float,
    web_vector_threshold: float | None = WEB_SEARCH_VECTOR_THRESHOLD,
) -> RelevanceGate:
    """待调门槛。数值必须来自 tune 集选择 + holdout 验证，不允许手填后直接上线。"""
    for label, value in (
        ("vector_threshold", vector_threshold),
        ("keyword_threshold", keyword_threshold),
        ("keyword_only_threshold", keyword_only_threshold),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{label} 必须在 0-1 之间")
    if web_vector_threshold is not None and not 0.0 <= web_vector_threshold <= 1.0:
        raise ValueError("web_vector_threshold 必须在 0-1 之间")
    return RelevanceGate(
        "candidate-threshold",
        vector_threshold,
        keyword_threshold,
        keyword_only_threshold,
        web_vector_threshold,
    )


def production_relevance_gate(
    *,
    web_vector_threshold: float | None = WEB_SEARCH_VECTOR_THRESHOLD,
) -> RelevanceGate:
    """返回经冻结 tune/holdout 验收的线上逐候选门槛。"""
    return candidate_threshold_gate(
        vector_threshold=PRODUCTION_VECTOR_THRESHOLD,
        keyword_threshold=PRODUCTION_KEYWORD_THRESHOLD,
        keyword_only_threshold=PRODUCTION_KEYWORD_ONLY_THRESHOLD,
        web_vector_threshold=web_vector_threshold,
    )


def gate_from_profile(
    profile: RelevanceGateProfile,
    *,
    vector_threshold: float | None = None,
    keyword_threshold: float | None = None,
    keyword_only_threshold: float | None = None,
) -> RelevanceGate:
    """按 profile 取名；`candidate-threshold` 必须同时给出三个阈值。"""
    if profile == "none":
        return no_gate()
    if profile == "current-consultation":
        return current_consultation_gate()
    if vector_threshold is None or keyword_threshold is None:
        raise ValueError("candidate-threshold 需要同时给出向量阈值与关键词阈值")
    return candidate_threshold_gate(
        vector_threshold=vector_threshold,
        keyword_threshold=keyword_threshold,
        keyword_only_threshold=(
            keyword_only_threshold if keyword_only_threshold is not None else keyword_threshold
        ),
    )


def _vector_threshold_for(scores: RelevanceScores, gate: RelevanceGate) -> float:
    assert gate.vector_threshold is not None
    if scores.source_key == WEB_SEARCH_SOURCE_KEY and gate.web_vector_threshold is not None:
        return gate.web_vector_threshold
    return gate.vector_threshold


def relevance_decision(scores: RelevanceScores, gate: RelevanceGate) -> RelevanceDecision:
    """逐候选判定。顺序与语义都按模块开头那四条纪律来，不看 `rerank_score`。"""
    if gate.profile == "none":
        return RelevanceDecision(True, "profile-none")

    vector_threshold = _vector_threshold_for(scores, gate)
    assert gate.keyword_threshold is not None
    assert gate.keyword_only_threshold is not None

    if scores.vector_similarity is None and scores.keyword_score is None:
        # legacy/mock：只有 similarity（评测桩、联网摘要）。兼容路径，单独记 reason。
        if scores.similarity >= vector_threshold:
            return RelevanceDecision(True, "legacy-similarity-at-or-above-threshold")
        return RelevanceDecision(False, "legacy-similarity-below-threshold")

    if scores.vector_similarity is not None and scores.vector_similarity >= vector_threshold:
        return RelevanceDecision(True, "vector-at-or-above-threshold")

    if scores.keyword_score is None:
        return RelevanceDecision(False, "vector-below-threshold")

    if scores.vector_similarity is None:
        # 没有当前向量：走单独的无向量关键词规则，避免精确命中被误杀。
        keep = scores.keyword_score >= gate.keyword_only_threshold
        return RelevanceDecision(
            keep,
            "keyword-only-at-or-above-threshold" if keep else "keyword-only-below-threshold",
        )

    # 有向量但向量分不足：关键词只能作补充证据，用更严的那个阈值。
    keep = scores.keyword_score >= gate.keyword_threshold
    return RelevanceDecision(
        keep, "keyword-at-or-above-threshold" if keep else "vector-below-threshold"
    )


def is_relevant(scores: RelevanceScores, gate: RelevanceGate) -> bool:
    return relevance_decision(scores, gate).keep


def scores_from_citation(item: RetrievalCitation) -> RelevanceScores:
    return RelevanceScores(
        similarity=item.similarity,
        keyword_score=item.keyword_score,
        vector_similarity=item.vector_similarity,
        rerank_score=item.rerank_score,
        source_key=item.source_key,
    )


def scores_from_mapping(item: Mapping[str, object]) -> RelevanceScores:
    """咨询图的 `RetrievalEvidence` 是 dict；评测断点里的候选记录也是 dict。"""

    def optional_float(key: str) -> float | None:
        value = item.get(key)
        if value is None:
            return None
        return float(value)  # type: ignore[arg-type]

    similarity = item.get("similarity")
    return RelevanceScores(
        similarity=float(similarity) if similarity is not None else 0.0,  # type: ignore[arg-type]
        keyword_score=optional_float("keyword_score"),
        vector_similarity=optional_float("vector_similarity"),
        rerank_score=optional_float("rerank_score"),
        source_key=str(item.get("source_key") or ""),
    )


def partition_relevant[T](
    rows: Sequence[T],
    gate: RelevanceGate,
    score_of: Callable[[T], RelevanceScores],
) -> list[T]:
    """逐候选过滤：**每一项**都单独判定，不是只看第一项。"""
    return [row for row in rows if is_relevant(score_of(row), gate)]


def decisions_for[T](
    rows: Iterable[T],
    gate: RelevanceGate,
    score_of: Callable[[T], RelevanceScores],
) -> list[RelevanceDecision]:
    return [relevance_decision(score_of(row), gate) for row in rows]


def filter_citations(
    items: Iterable[RetrievalCitation],
    gate: RelevanceGate,
) -> list[RetrievalCitation]:
    return partition_relevant(list(items), gate, scores_from_citation)


def filter_evidence[T: Mapping[str, object]](
    items: Iterable[T],
    gate: RelevanceGate,
) -> list[T]:
    """咨询图/断点里的证据是 dict（`RetrievalEvidence`）。"""
    return partition_relevant(list(items), gate, scores_from_mapping)
