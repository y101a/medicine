"""Optional graph context, strictly limited to already cited approved RAG evidence."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.graph.state import RetrievalEvidence
from app.services.knowledge_graph_query import (
    explore_public_graph,
    find_public_question_concepts,
)


async def build_public_graph_context(
    db: AsyncSession,
    user_text: str,
    rag_items: list[RetrievalEvidence],
) -> tuple[str | None, int]:
    """Return at most five relations; never introduce an unnumbered source."""

    concepts = await find_public_question_concepts(db, user_text)
    if len(concepts) != 1:
        return None, 0
    graph = await explore_public_graph(db, concepts[0].id)
    if not graph.available:
        return None, 0
    approved_chunks = {
        item["chunk_id"]: index
        for index, item in enumerate(rag_items, start=1)
        if item["trust_level"] == "approved" and item.get("chunk_id")
    }
    matched = []
    for relation in graph.relations:
        source_numbers = sorted(
            {
                approved_chunks[evidence["chunkId"]]
                for evidence in relation.evidence
                if evidence["chunkId"] in approved_chunks
            }
        )
        if not source_numbers:
            continue
        matched.append(
            {
                "subject": relation.subject_name,
                "predicate": relation.predicate,
                "object": relation.object_name,
                "sourceNumbers": source_numbers,
            }
        )
        if len(matched) >= 5:
            break
    if not matched:
        return None, 0
    context = (
        "公共医学图谱关系（仅供组织科普回答；不是诊断；仅使用已编号的审核来源，"
        "不得新增无依据事实）：\n"
        + json.dumps(matched, ensure_ascii=False)
    )
    return context, len(matched)
