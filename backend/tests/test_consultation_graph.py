from datetime import UTC, datetime
from uuid import uuid4

from app.ai.graph import (
    consultation_generation_graph,
    consultation_graph,
    render_rag_context,
    run_consultation_safety,
)
from app.ai.graph.retrieval_gate import evaluate_retrieval_gate
from app.ai.graph.workflow import build_consultation_generation_graph
from app.rag.retrieval import RetrievalCitation, RetrievalError, RetrievalResult
from app.safety import TRIAGE_RULESET_VERSION


async def test_emergency_input_routes_to_emergency_end_without_raw_text():
    result = await run_consultation_safety("家人现在喘不上气")

    assert result["triage_route"] == "emergency"
    assert result["next_step"] == "emergency_end"
    assert result["triage_rule_version"] == TRIAGE_RULESET_VERSION
    assert result["triage_rule_ids"] == ["severe_breathing_problem"]
    assert result["triage_result"] is not None
    assert "user_text" not in result
    assert "喘不上气" not in str(result)


async def test_safe_input_routes_to_generation_extension_point():
    result = await run_consultation_safety("我想了解普通头痛有哪些常见原因")

    assert result == {
        "triage_route": "continue",
        "triage_rule_version": TRIAGE_RULESET_VERSION,
        "triage_rule_ids": [],
        "triage_result": None,
        "next_step": "generation_ready",
    }


def test_graph_contains_the_safety_gate_and_both_terminal_branches():
    node_names = set(consultation_graph.get_graph().nodes)

    assert {"triage", "emergency", "generation_ready"}.issubset(node_names)


def retrieval_result() -> RetrievalResult:
    return RetrievalResult(
        query_redacted=False,
        model="qwen3.7-text-embedding-flash",
        version="2026-09-01",
        items=[
            RetrievalCitation(
                chunk_id=uuid4(),
                document_id=uuid4(),
                source_key="developer_prototype_knowledge",
                organization="项目开发者",
                title="头痛科普原型资料",
                canonical_url="https://prototype.invalid/medical-knowledge/headache",
                section_title="常见情况",
                version_label="prototype-test",
                published_at=datetime.now(UTC),
                content="用于隔离测试的头痛科普证据。",
                similarity=0.88,
                trust_level="prototype",
            )
        ],
    )


async def test_generation_graph_retrieves_after_safe_triage_without_leaking_input():
    calls: list[str] = []

    async def fake_retriever(_db, query: str, *, top_k: int):
        calls.append(query)
        assert top_k == 4
        return retrieval_result()

    graph = build_consultation_generation_graph(fake_retriever)
    result = await graph.ainvoke({"user_text": "普通头痛科普", "db": object()})

    assert calls == ["普通头痛科普"]
    assert result["next_step"] == "generation_ready"
    assert result["retrieval_status"] == "completed"
    assert result["retrieval_intent"] is True
    assert result["retrieval_gate_reason"] == "medical_content"
    assert result["retrieval_items"][0]["trust_level"] == "prototype"
    assert "user_text" not in result
    assert "db" not in result


async def test_generation_graph_skips_retrieval_on_emergency():
    async def unexpected_retriever(*_args, **_kwargs):
        raise AssertionError("红旗命中后不应执行检索")

    graph = build_consultation_generation_graph(unexpected_retriever)
    result = await graph.ainvoke({"user_text": "突然胸痛喘不上气", "db": object()})

    assert result["next_step"] == "emergency_end"
    assert result["retrieval_status"] == "skipped"
    assert result["retrieval_gate_reason"] == "emergency"
    assert result["retrieval_items"] == []


async def test_generation_graph_marks_controlled_retrieval_failure():
    async def failed_retriever(*_args, **_kwargs):
        raise RetrievalError(504, "EMBEDDING_TIMEOUT", "向量服务超时")

    graph = build_consultation_generation_graph(failed_retriever)
    result = await graph.ainvoke({"user_text": "普通头痛科普", "db": object()})

    assert result["retrieval_status"] == "failed"
    assert result["retrieval_error_code"] == "EMBEDDING_TIMEOUT"
    assert result["next_step"] == "generation_ready"


async def test_generation_graph_skips_retrieval_for_normal_chat():
    async def unexpected_retriever(*_args, **_kwargs):
        raise AssertionError("普通聊天不应执行检索")

    graph = build_consultation_generation_graph(unexpected_retriever)
    result = await graph.ainvoke({"user_text": "你好，你是什么模型", "db": object()})

    assert result["next_step"] == "generation_ready"
    assert result["retrieval_status"] == "skipped"
    assert result["retrieval_intent"] is False
    assert result["retrieval_gate_reason"] == "non_medical_content"


def test_rag_context_labels_prototype_evidence():
    item = retrieval_result().items[0]
    context = render_rag_context(
        [
            {
                "source_key": item.source_key,
                "organization": item.organization,
                "title": item.title,
                "canonical_url": item.canonical_url,
                "section_title": item.section_title,
                "content": item.content,
                "similarity": item.similarity,
                "trust_level": item.trust_level,
            }
        ]
    )

    assert context is not None
    assert '"id": "来源1"' in context
    assert '"trust_level": "prototype"' in context
    assert "普通头痛科普" not in context


def test_generation_graph_contains_rag_between_triage_and_ready():
    node_names = set(consultation_generation_graph.get_graph().nodes)

    assert {
        "triage",
        "emergency",
        "retrieval_gate",
        "retrieve",
        "generation_ready",
    }.issubset(node_names)


def test_retrieval_gate_separates_medical_questions_from_normal_chat():
    medical_inputs = [
        "我头痛两天了",
        "普通感冒是否应该服用抗生素",
        "什么是高血压",
        "体检发现血糖偏高怎么办",
        "被狗咬伤应该挂哪个科",
        "鼻炎怎么办",
        "最近胃不舒服",
    ]
    normal_inputs = [
        "你好",
        "你是什么模型",
        "帮我写一段代码",
        "怎么切换模型",
        "如何使用这个系统",
        "讲个笑话",
        "这个病理科普卡片怎么开启",
    ]

    assert all(evaluate_retrieval_gate(text).should_retrieve for text in medical_inputs)
    assert not any(evaluate_retrieval_gate(text).should_retrieve for text in normal_inputs)


def _citation(
    slug: str,
    *,
    similarity: float,
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
        section_title="常见情况",
        version_label="prototype-test",
        published_at=datetime.now(UTC),
        content="用于隔离测试的原型证据。",
        similarity=similarity,
        trust_level="prototype",
        keyword_score=keyword,
        vector_similarity=vector,
    )


def _result(*items: RetrievalCitation) -> RetrievalResult:
    return RetrievalResult(
        query_redacted=False,
        model="qwen3.7-text-embedding-flash",
        version="2026-09-01",
        items=list(items),
    )


async def test_generation_graph_returns_empty_evidence_without_breaking_the_answer_path():
    """§4.6：证据全被门槛拦下时，检索标记为空、不产出任何引用，但回答链路照常继续。"""

    async def weak_retriever(_db, _query: str, *, top_k: int):
        assert top_k == 4
        return _result(_citation("headache", similarity=0.31, vector=0.31))

    graph = build_consultation_generation_graph(weak_retriever)
    result = await graph.ainvoke({"user_text": "普通头痛科普", "db": object()})

    assert result["retrieval_status"] == "empty"
    assert result["retrieval_items"] == []
    assert result["next_step"] == "generation_ready"
    assert result["retrieval_intent"] is True


async def test_generation_graph_keeps_unembedded_exact_keyword_evidence():
    """§4.6/§4.3：没有当前向量但关键词精确命中的证据，不能在咨询链路里被误杀。"""

    async def keyword_retriever(_db, _query: str, *, top_k: int):
        return _result(_citation("crohn", similarity=0.0, keyword=1.0))

    graph = build_consultation_generation_graph(keyword_retriever)
    result = await graph.ainvoke({"user_text": "普通头痛科普", "db": object()})

    assert result["retrieval_status"] == "completed"
    assert len(result["retrieval_items"]) == 1
    assert result["retrieval_items"][0]["keyword_score"] == 1.0


async def test_generation_graph_filters_candidates_one_by_one():
    """§4.1：同一次召回里，低分候选被删、高分候选保留（不是只看第一项）。"""

    async def mixed_retriever(_db, _query: str, *, top_k: int):
        return _result(
            _citation("weak-first", similarity=0.2, vector=0.2),
            _citation("strong-later", similarity=0.9, vector=0.93),
        )

    graph = build_consultation_generation_graph(mixed_retriever)
    result = await graph.ainvoke({"user_text": "普通头痛科普", "db": object()})

    assert result["retrieval_status"] == "completed"
    assert [item["title"] for item in result["retrieval_items"]] == ["strong-later"]
