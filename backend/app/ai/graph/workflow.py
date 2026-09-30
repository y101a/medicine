import json
from collections.abc import Awaitable, Callable
from typing import Literal, cast

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.graph.nodes import emergency_node, generation_ready_node, triage_node
from app.ai.graph.retrieval_gate import evaluate_retrieval_gate
from app.ai.graph.state import (
    ConsultationGenerationGraphInput,
    ConsultationGenerationGraphOutput,
    ConsultationGenerationGraphState,
    ConsultationGraphInput,
    ConsultationGraphOutput,
    ConsultationGraphState,
    RetrievalEvidence,
)
from app.core.config import get_settings
from app.rag.relevance import (
    CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD,
    CURRENT_CONSULTATION_KEYWORD_THRESHOLD,
    candidate_threshold_gate,
    filter_evidence,
    is_relevant,
    production_relevance_gate,
    scores_from_mapping,
)
from app.rag.retrieval import RetrievalError, RetrievalResult, search_knowledge
from app.rag.web_search import (
    SOURCE_KEY,
    SearchHit,
    WebSearchError,
    broad_coverage_limited,
    generic_topic,
    save_search_prototypes,
    search_generic_topic,
    topic_matches_text,
    trusted_organization,
    web_hit_limit,
)

Retriever = Callable[..., Awaitable[RetrievalResult]]
WebSearcher = Callable[[str], Awaitable[list[SearchHit]]]
RAG_TOP_K = 4


def route_after_triage(
    state: ConsultationGraphState,
) -> Literal["emergency", "generation_ready"]:
    if state["triage_route"] == "emergency":
        return "emergency"
    return "generation_ready"


def build_consultation_graph():
    builder = StateGraph(
        ConsultationGraphState,
        input_schema=ConsultationGraphInput,
        output_schema=ConsultationGraphOutput,
    )
    builder.add_node("triage", triage_node)
    builder.add_node("emergency", emergency_node)
    builder.add_node("generation_ready", generation_ready_node)
    builder.add_edge(START, "triage")
    builder.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "emergency": "emergency",
            "generation_ready": "generation_ready",
        },
    )
    builder.add_edge("emergency", END)
    builder.add_edge("generation_ready", END)
    return builder.compile()


# Deliberately compiled without a checkpointer: raw health text is not additionally persisted.
consultation_graph = build_consultation_graph()


def _evidence_item(item) -> RetrievalEvidence:
    return {
        "source_key": item.source_key,
        "organization": item.organization,
        "title": item.title,
        "canonical_url": item.canonical_url,
        "section_title": item.section_title,
        "content": item.content,
        "similarity": item.similarity,
        "trust_level": item.trust_level,
        "keyword_score": item.keyword_score,
        "vector_similarity": item.vector_similarity,
        "rerank_score": item.rerank_score,
    }


def _retrieval_item_is_relevant(item: RetrievalEvidence, threshold: float) -> bool:
    """历史兼容层：旧调用点是「给我一个显式阈值」的口径。

    真正的判定已经统一到 `app.rag.relevance`（全项目唯一一份），这里只是把「一个显式阈值 +
    固定关键词 0.2 + 不区分来源」翻译成同一套 gate，避免再出现第二份数字。
    """
    return is_relevant(
        scores_from_mapping(item),
        candidate_threshold_gate(
            vector_threshold=threshold,
            keyword_threshold=CURRENT_CONSULTATION_KEYWORD_THRESHOLD,
            keyword_only_threshold=CURRENT_CONSULTATION_KEYWORD_ONLY_THRESHOLD,
            web_vector_threshold=None,
        ),
    )


# 门槛数字只有 `app.rag.relevance` 一份。2026-09-30 冻结评测通过后，咨询图启用
# 0.56/0.2/0.2；命中泛化主题时网页缓存仍沿用独立 0.60，未命中时与其他来源同为 0.56。
TOPIC_RELEVANCE_GATE = production_relevance_gate()
PLAIN_RELEVANCE_GATE = production_relevance_gate(
    web_vector_threshold=None,
)


def build_consultation_generation_graph(
    retriever: Retriever = search_knowledge,
    web_searcher: WebSearcher = search_generic_topic,
):
    async def retrieval_node(
        state: ConsultationGenerationGraphInput,
    ) -> dict[str, object]:
        try:
            result = await retriever(
                state["db"],
                state["user_text"],
                top_k=RAG_TOP_K,
            )
        except RetrievalError as exc:
            return {
                "retrieval_status": "failed",
                "retrieval_items": [],
                "retrieval_error_code": exc.code,
                "web_search_status": "skipped",
                "web_search_error_code": None,
            }
        items = [_evidence_item(item) for item in result.items]
        topic = generic_topic(state["user_text"])
        if topic:
            items = filter_evidence(
                [
                    item
                    for item in items
                    if topic_matches_text(topic, item["title"] + item["content"])
                ],
                TOPIC_RELEVANCE_GATE,
            )
        else:
            items = filter_evidence(items, PLAIN_RELEVANCE_GATE)
        return {
            "retrieval_status": "completed" if items else "empty",
            "retrieval_items": items,
            "retrieval_error_code": None,
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    async def web_search_node(
        state: ConsultationGenerationGraphState,
    ) -> dict[str, object]:
        topic = generic_topic(state["user_text"])
        if not topic:
            return {"web_search_status": "skipped"}
        try:
            hits = await web_searcher(topic)
        except WebSearchError as exc:
            return {
                "web_search_status": "failed",
                "web_search_error_code": exc.code,
            }
        except Exception:
            return {
                "web_search_status": "failed",
                "web_search_error_code": "WEB_SEARCH_UNAVAILABLE",
            }
        hits = [
            hit
            for hit in hits
            if trusted_organization(hit.url) == hit.organization
            and topic_matches_text(topic, hit.title + hit.excerpt)
        ][: web_hit_limit(topic)]
        items: list[RetrievalEvidence] = [
            {
                "source_key": SOURCE_KEY,
                "organization": hit.organization,
                "title": hit.title,
                "canonical_url": hit.url,
                "section_title": "联网搜索摘要（未经医学审核）",
                "content": hit.excerpt,
                "similarity": 0.0,
                "trust_level": "prototype",
            }
            for hit in hits
        ]
        if items:
            try:
                async with state["db"].begin_nested():
                    await save_search_prototypes(state["db"], topic, hits)
            except Exception:
                # Live citations can still be used if prototype caching fails.
                pass
        combined_items = list(state["retrieval_items"])
        seen_urls = {item["canonical_url"] for item in combined_items}
        for item in items:
            if item["canonical_url"] not in seen_urls:
                combined_items.append(item)
                seen_urls.add(item["canonical_url"])
        return {
            "web_search_status": "completed" if items else "empty",
            "web_search_error_code": None,
            "retrieval_status": "completed" if combined_items else state["retrieval_status"],
            "retrieval_items": combined_items,
        }

    def emergency_generation_node(_state: object) -> dict[str, object]:
        return {
            "next_step": "emergency_end",
            "retrieval_status": "skipped",
            "retrieval_items": [],
            "retrieval_error_code": None,
            "retrieval_intent": False,
            "retrieval_gate_reason": "emergency",
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    def retrieval_gate_node(
        state: ConsultationGenerationGraphInput,
    ) -> dict[str, object]:
        decision = evaluate_retrieval_gate(state["user_text"])
        if decision.should_retrieve:
            return {
                "retrieval_intent": True,
                "retrieval_gate_reason": decision.reason,
            }
        return {
            "retrieval_intent": False,
            "retrieval_gate_reason": decision.reason,
            "retrieval_status": "skipped",
            "retrieval_items": [],
            "retrieval_error_code": None,
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    def route_after_retrieval_gate(
        state: ConsultationGenerationGraphState,
    ) -> Literal["retrieve", "generation_ready"]:
        return "retrieve" if state["retrieval_intent"] else "generation_ready"

    def route_after_retrieval(
        state: ConsultationGenerationGraphState,
    ) -> Literal["web_search", "generation_ready"]:
        topic = generic_topic(state["user_text"])
        coverage_limited = broad_coverage_limited(
            topic,
            [item["title"] + item["content"] for item in state["retrieval_items"]],
        )
        if (
            get_settings().app_environment == "development"
            and topic
            and (state["retrieval_status"] == "empty" or coverage_limited)
        ):
            return "web_search"
        return "generation_ready"

    builder = StateGraph(
        ConsultationGenerationGraphState,
        input_schema=ConsultationGenerationGraphInput,
        output_schema=ConsultationGenerationGraphOutput,
    )
    builder.add_node("triage", triage_node)
    builder.add_node("emergency", emergency_generation_node)
    builder.add_node("retrieval_gate", retrieval_gate_node)
    builder.add_node("retrieve", retrieval_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("generation_ready", generation_ready_node)
    builder.add_edge(START, "triage")
    builder.add_conditional_edges(
        "triage",
        route_after_triage,
        {"emergency": "emergency", "generation_ready": "retrieval_gate"},
    )
    builder.add_edge("emergency", END)
    builder.add_conditional_edges(
        "retrieval_gate",
        route_after_retrieval_gate,
        {"retrieve": "retrieve", "generation_ready": "generation_ready"},
    )
    builder.add_conditional_edges(
        "retrieve",
        route_after_retrieval,
        {"web_search": "web_search", "generation_ready": "generation_ready"},
    )
    builder.add_edge("web_search", "generation_ready")
    builder.add_edge("generation_ready", END)
    return builder.compile()


consultation_generation_graph = build_consultation_generation_graph()


async def run_consultation_safety(user_text: str) -> ConsultationGraphOutput:
    result = await consultation_graph.ainvoke({"user_text": user_text})
    return cast(ConsultationGraphOutput, result)


async def run_consultation_generation(
    user_text: str,
    db: AsyncSession,
) -> ConsultationGenerationGraphOutput:
    result = await consultation_generation_graph.ainvoke({"user_text": user_text, "db": db})
    return cast(ConsultationGenerationGraphOutput, result)


def render_rag_context(items: list[RetrievalEvidence]) -> str | None:
    if not items:
        return None
    sources = [
        {
            "id": f"来源{index}",
            "organization": item["organization"],
            "title": item["title"],
            "url": item["canonical_url"],
            "section": item["section_title"],
            "trust_level": item["trust_level"],
            "content": item["content"],
        }
        for index, item in enumerate(items, start=1)
    ]
    return json.dumps(sources, ensure_ascii=False)
