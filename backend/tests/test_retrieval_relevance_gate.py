"""检索相关度门槛的单元测试（`RETRIEVAL_RELEVANCE_GATE_PLAN.md` §4 第 1-5、9 条）。

全部是**纯函数**测试：不连数据库、不调用向量服务、不跑评测。门槛的价值恰恰在于
「能事后复算、能说清为什么」，所以这里逐条锁住分数语义，而不是只看一个 yes/no：

- 逐候选过滤（不是只看第一项）；
- 第一项低于门槛不能挡住后面的合格候选；
- 无向量精确关键词命中不被误杀，而普通弱关键词也不能靠 0.2 的宽松规则放行；
- `rerank_score` 再高也不能单独充当医学证据；
- 三种模式的分数语义不混用；网页来源用自己那档阈值。
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.ai.graph.workflow import _retrieval_item_is_relevant
from app.rag.relevance import (
    CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD,
    CURRENT_CONSULTATION_KEYWORD_THRESHOLD,
    CURRENT_CONSULTATION_VECTOR_THRESHOLD,
    PRODUCTION_KEYWORD_ONLY_THRESHOLD,
    PRODUCTION_KEYWORD_THRESHOLD,
    PRODUCTION_VECTOR_THRESHOLD,
    WEB_SEARCH_SOURCE_KEY,
    RelevanceScores,
    candidate_threshold_gate,
    current_consultation_gate,
    filter_citations,
    filter_evidence,
    gate_from_profile,
    is_relevant,
    no_gate,
    production_relevance_gate,
    relevance_decision,
    scores_from_citation,
    scores_from_mapping,
)
from app.rag.retrieval import RetrievalCitation


def scores(
    similarity: float = 0.9,
    *,
    keyword: float | None = None,
    vector: float | None = None,
    rerank: float | None = None,
    source_key: str = "developer_prototype_knowledge",
) -> RelevanceScores:
    return RelevanceScores(
        similarity=similarity,
        keyword_score=keyword,
        vector_similarity=vector,
        rerank_score=rerank,
        source_key=source_key,
    )


def evidence(
    slug: str,
    similarity: float = 0.9,
    *,
    keyword: float | None = None,
    vector: float | None = None,
    rerank: float | None = None,
    source_key: str = "developer_prototype_knowledge",
) -> dict[str, object]:
    """咨询图口径的证据（`RetrievalEvidence`）：dict，字段与线上一致。"""
    return {
        "source_key": source_key,
        "organization": "项目开发者",
        "title": slug,
        "canonical_url": f"https://prototype.invalid/medical-knowledge/{slug}",
        "section_title": "测试",
        "content": "隔离测试内容",
        "similarity": similarity,
        "trust_level": "prototype",
        "keyword_score": keyword,
        "vector_similarity": vector,
        "rerank_score": rerank,
    }


def citation(
    slug: str,
    similarity: float = 0.9,
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


def test_gate_removes_every_candidate_below_the_threshold_not_only_the_first():
    """§4.1：低于门槛的候选要**逐项**被删，不是只检查第一项。"""
    rows = [
        evidence("strong", 0.9, vector=0.93),
        evidence("weak", 0.9, vector=0.31),
        evidence("keyword-only", 0.9, keyword=1.0),
        evidence("legacy", 0.8),
    ]

    kept = filter_evidence(rows, current_consultation_gate())

    assert [row["title"] for row in kept] == ["strong", "keyword-only", "legacy"]


def test_first_candidate_below_threshold_does_not_hide_later_candidates():
    """§4.2：首项不达标时，后面的合格候选必须仍然留下。"""
    rows = [evidence("weak-first", 0.9, vector=0.2), evidence("strong-later", 0.9, vector=0.95)]

    kept = filter_evidence(rows, current_consultation_gate())

    assert [row["title"] for row in kept] == ["strong-later"]


def test_threshold_equality_is_inclusive_on_every_path():
    """§6.2：相等时放行（`>=`），刚好差一点则拦下——否则边界无人锁。"""
    gate = current_consultation_gate()

    assert is_relevant(scores(0.9, vector=CURRENT_CONSULTATION_VECTOR_THRESHOLD), gate) is True
    just_below_vector = scores(0.9, vector=CURRENT_CONSULTATION_VECTOR_THRESHOLD - 0.0001)
    assert is_relevant(just_below_vector, gate) is False
    assert is_relevant(scores(CURRENT_CONSULTATION_VECTOR_THRESHOLD), gate) is True
    assert is_relevant(scores(CURRENT_CONSULTATION_VECTOR_THRESHOLD - 0.0001), gate) is False
    assert (
        is_relevant(
            scores(0.9, keyword=CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD), gate
        )
        is True
    )
    assert (
        is_relevant(
            scores(0.9, keyword=CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD - 0.0001), gate
        )
        is False
    )


def test_keyword_only_candidate_without_a_vector_is_kept():
    """§4.3 前半：没有当前向量、但关键词精确命中的候选不能被误杀（既有回归保护的行为）。"""
    gate = current_consultation_gate()

    decision = relevance_decision(scores(0.9, keyword=1.0), gate)
    assert decision.keep is True
    assert decision.reason == "keyword-only-at-or-above-threshold"

    weak = relevance_decision(scores(0.9, keyword=0.05), gate)
    assert weak.keep is False
    assert weak.reason == "keyword-only-below-threshold"


def test_weak_keyword_cannot_rescue_a_low_vector_candidate_under_a_tight_gate():
    """§4.3 后半：普通弱关键词不得靠 0.2 的宽松规则把无关文档放进来。"""
    weak = scores(0.9, keyword=0.25, vector=0.3)
    assert is_relevant(weak, current_consultation_gate()) is True  # 历史规则就是 0.2，行为可查

    tight = candidate_threshold_gate(
        vector_threshold=0.55,
        keyword_threshold=0.5,
        keyword_only_threshold=0.2,
    )
    assert is_relevant(weak, tight) is False


def test_high_rerank_score_never_admits_a_candidate():
    """§4.4：`rerank_score` 很高但向量/关键词证据不足时不得放行。"""
    gate = current_consultation_gate()

    decision = relevance_decision(scores(0.0, vector=0.1, rerank=1.0), gate)
    assert decision.keep is False
    assert decision.reason == "vector-below-threshold"

    keyword_only_rerank = relevance_decision(scores(0.0, keyword=0.05, rerank=1.0), gate)
    assert keyword_only_rerank.keep is False


def test_score_semantics_do_not_mix_between_the_three_modes():
    """§4.5：向量分/关键词分/`rerank_score` 各有各的规则，不能互相顶替。"""
    # (a) 有向量：向量分说了算（关键词分高也救不了低向量，除非达到关键词阈值）
    vector_mode = scores(0.0, vector=0.6, keyword=None)
    assert is_relevant(vector_mode, current_consultation_gate()) is False
    # (b) 无向量：走无向量关键词规则
    keyword_mode = scores(0.0, keyword=0.3, vector=None)
    assert is_relevant(keyword_mode, current_consultation_gate()) is True
    # (c) 只有 rerank：不算证据
    rerank_only = scores(0.0, rerank=0.99)
    assert is_relevant(rerank_only, current_consultation_gate()) is False
    # (d) legacy 只有 similarity：用向量门槛比较
    legacy = scores(0.75)
    assert is_relevant(legacy, current_consultation_gate()) is True
    assert is_relevant(scores(0.71), current_consultation_gate()) is False


def test_web_search_source_uses_its_own_vector_threshold():
    """网页缓存语料是另一种来源：0.66 过、0.59 不过，普通来源 0.66 不过。"""
    gate = current_consultation_gate()

    assert is_relevant(scores(0.0, vector=0.66, source_key=WEB_SEARCH_SOURCE_KEY), gate) is True
    assert is_relevant(scores(0.0, vector=0.59, source_key=WEB_SEARCH_SOURCE_KEY), gate) is False
    assert is_relevant(scores(0.0, vector=0.66), gate) is False
    assert is_relevant(scores(0.0, vector=0.8), gate) is True


def test_no_gate_keeps_everything_and_says_so():
    """`none` 是评测基线与「线上维持原样」用的 profile：一条都不能少，且 reason 可区分。"""
    rows = [evidence("a", 0.01), evidence("b", 0.99, vector=0.99)]

    kept = filter_evidence(rows, no_gate())

    assert [row["title"] for row in kept] == ["a", "b"]
    assert relevance_decision(scores(0.01), no_gate()).reason == "profile-none"


def test_legacy_similarity_path_is_recorded_separately():
    """§B.4：兼容路径必须能与真实向量证据区分开，报告里才看得出哪些是 legacy。"""
    decision = relevance_decision(scores(0.8), current_consultation_gate())

    assert decision.keep is True
    assert decision.reason == "legacy-similarity-at-or-above-threshold"


def test_candidate_threshold_gate_rejects_out_of_range_values():
    with pytest.raises(ValueError, match="vector_threshold"):
        candidate_threshold_gate(
            vector_threshold=1.2,
            keyword_threshold=0.5,
            keyword_only_threshold=0.2,
        )
    with pytest.raises(ValueError, match="keyword_threshold"):
        candidate_threshold_gate(
            vector_threshold=0.5,
            keyword_threshold=-0.1,
            keyword_only_threshold=0.2,
        )
    with pytest.raises(ValueError, match="web_vector_threshold"):
        candidate_threshold_gate(
            vector_threshold=0.5,
            keyword_threshold=0.5,
            keyword_only_threshold=0.2,
            web_vector_threshold=2.0,
        )


def test_gate_from_profile_requires_thresholds_for_candidate_profile():
    assert gate_from_profile("none").profile == "none"
    assert gate_from_profile("current-consultation").profile == "current-consultation"
    with pytest.raises(ValueError, match="candidate-threshold"):
        gate_from_profile("candidate-threshold", vector_threshold=0.5)
    gate = gate_from_profile(
        "candidate-threshold",
        vector_threshold=0.55,
        keyword_threshold=0.5,
        keyword_only_threshold=0.2,
    )
    assert gate.vector_threshold == 0.55
    # 没给「无向量关键词」阈值时沿用同一数字，避免出现一个隐式默认值。
    assert gate.keyword_only_threshold == 0.2


def test_gate_identity_covers_profile_and_every_threshold():
    """§4.9 的前提：断点身份必须包含 profile 与**全部**阈值，且同参数稳定（无时间戳等易变值）。"""
    first = current_consultation_gate()
    second = current_consultation_gate()

    assert first.identity() == second.identity()
    identity = first.identity()
    assert identity["profile"] == "current-consultation"
    assert identity["vector"] == CURRENT_CONSULTATION_VECTOR_THRESHOLD
    assert identity["keyword"] == CURRENT_CONSULTATION_KEYWORD_THRESHOLD
    assert identity["keywordOnly"] == CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD
    assert identity["webVector"] == 0.60

    other = candidate_threshold_gate(
        vector_threshold=0.55,
        keyword_threshold=0.5,
        keyword_only_threshold=0.2,
    )
    assert other.identity() != identity


def test_workflow_compat_helper_matches_the_shared_gate():
    """阶段 B 的「行为不变」由这条锁住：旧调用点的口径等于同一套 gate 的一个实例。"""
    for item in (
        evidence("legacy", 0.72),
        evidence("legacy-low", 0.71),
        evidence("vector", 0.9, vector=0.71),
        evidence("keyword", 0.9, keyword=0.2),
        evidence("keyword-weak", 0.9, keyword=0.19),
    ):
        legacy_compat = candidate_threshold_gate(
            vector_threshold=CURRENT_CONSULTATION_VECTOR_THRESHOLD,
            keyword_threshold=CURRENT_CONSULTATION_KEYWORD_THRESHOLD,
            keyword_only_threshold=CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD,
            web_vector_threshold=None,
        )
        assert _retrieval_item_is_relevant(
            item, CURRENT_CONSULTATION_VECTOR_THRESHOLD
        ) is is_relevant(scores_from_mapping(item), legacy_compat)

    assert _retrieval_item_is_relevant(evidence("legacy", 0.72), 0.72) is True
    assert _retrieval_item_is_relevant(evidence("legacy", 0.71), 0.72) is False


def test_filter_citations_works_on_the_api_level_type():
    """/knowledge/search 与文档生成用的是 `RetrievalCitation`，同样逐项过滤。"""
    items = [
        citation("keep", 0.9, vector=0.93),
        citation("drop", 0.9, vector=0.2),
    ]

    kept = filter_citations(items, current_consultation_gate())

    assert [item.title for item in kept] == ["keep"]
    assert scores_from_citation(items[0]).vector_similarity == 0.93


def test_production_gate_uses_only_the_frozen_validated_thresholds():
    gate = production_relevance_gate()

    assert PRODUCTION_VECTOR_THRESHOLD == 0.56
    assert PRODUCTION_KEYWORD_THRESHOLD == 0.2
    assert PRODUCTION_KEYWORD_ONLY_THRESHOLD == 0.2
    assert gate.thresholds() == {
        "vector": 0.56,
        "keyword": 0.2,
        "keywordOnly": 0.2,
        "webVector": 0.60,
    }
    assert is_relevant(scores(vector=0.56), gate) is True
    assert is_relevant(scores(vector=0.559999), gate) is False
    assert is_relevant(scores(keyword=0.2), gate) is True
    assert is_relevant(
        scores(vector=0.599999, source_key=WEB_SEARCH_SOURCE_KEY), gate
    ) is False
