"""Paid P0/P1 comparison on public synthetic questions; never persists chat.

This is an engineering benchmark, not medical correctness or a blinded eval.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from time import perf_counter

from app.ai.consultation_evidence_reviewer import check_answer_evidence, reviewable_answer
from app.ai.consultation_planner import plan_consultation_answer
from app.ai.graph import render_rag_context, run_consultation_generation
from app.ai.no_evidence import no_evidence_reply, unverified_web_risk_reply
from app.ai.provider import stream_chat
from app.ai.registry import get_model
from app.db.session import SessionLocal
from app.rag.citation_audit import audit_answer_citations

CASES = (
    ("covered_dizziness", "头晕和眩晕有什么区别？"),
    ("covered_uti", "尿路感染的尿频尿急尿痛是什么？"),
)
PUBLIC_EVAL_SOURCE_KEYS = frozenset({"developer_prototype_knowledge"})


async def _answer(question: str, model, graph: dict, *, p1: bool) -> dict:
    sources = graph["retrieval_items"]
    history = [{"role": "user", "content": question}]
    calls = 0
    start = perf_counter()
    if p1:
        try:
            guidance = await plan_consultation_answer(model, question)
            history.insert(
                0, {"role": "user", "content": "回答组织建议（非医学证据）：" + guidance}
            )
            calls += 1
        except Exception:
            pass
    draft = "".join(
        [chunk async for chunk in stream_chat(history, model, "plain", render_rag_context(sources))]
    )
    calls += 1
    content = draft
    reviewer_status = "skipped"
    if p1:
        review_sources = [
            {"reference_number": index, "title": item["title"], "content": item["content"]}
            for index, item in enumerate(sources, start=1)
        ]
        if reviewable_answer(draft, review_sources):
            try:
                content = await check_answer_evidence(model, draft, review_sources)
                calls += 1
                reviewer_status = "completed"
            except Exception:
                reviewer_status = "failed"
    snapshots = [
        {"reference_number": index, "title": item["title"]}
        for index, item in enumerate(sources, start=1)
    ]
    checked, citations = audit_answer_citations(content, snapshots)
    return {
        "mode": "p1" if p1 else "p0",
        "elapsed_ms": round((perf_counter() - start) * 1000),
        "model_calls_succeeded": calls,
        "reviewer_status": reviewer_status,
        "draft_paragraphs": len(draft.split("\n\n")),
        "final_paragraphs": len(checked.split("\n\n")),
        "answer_chars": len(checked),
        "cited_source_count": len(citations),
        "has_safety_notice": "不作确诊" in checked,
        "has_unverified_reference": "[引用未核实]" in checked,
    }


async def main(case_id_filter: str | None = None) -> None:
    model = get_model("qwen3.8-flash")
    for case_id, question in CASES:
        if case_id_filter and case_id != case_id_filter:
            continue
        async with SessionLocal() as db:
            try:
                graph = await run_consultation_generation(question, db)
                fallback = no_evidence_reply(question, graph) or unverified_web_risk_reply(
                    question, graph
                )
                if graph["triage_route"] != "continue" or fallback:
                    print(
                        json.dumps(
                            {"case_id": case_id, "status": "skipped_safety_or_no_evidence"},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    continue
                if not graph["retrieval_items"] or any(
                    item["source_key"] not in PUBLIC_EVAL_SOURCE_KEYS
                    for item in graph["retrieval_items"]
                ):
                    print(
                        json.dumps(
                            {"case_id": case_id, "status": "skipped_non_public_source"},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    continue
                for p1 in (False, True):
                    result = await _answer(question, model, graph, p1=p1)
                    print(
                        json.dumps(
                            {
                                "case_id": case_id,
                                "source_count": len(graph["retrieval_items"]),
                                **result,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            finally:
                await db.rollback()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", choices=[item[0] for item in CASES])
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error("真实 P0/P1 对照会调用外部模型，必须显式传入 --allow-paid")
    asyncio.run(main(args.case_id))
