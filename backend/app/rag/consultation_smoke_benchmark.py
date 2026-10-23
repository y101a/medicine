"""Small synthetic consultation smoke run; not a clinical answer benchmark.

Run only with explicit permission for paid model/embedding and network calls.
Does not create a user or persist chat messages; any web-cache writes are rolled back.
"""

import argparse
import asyncio
import json
from time import perf_counter

from app.ai.graph import render_rag_context, run_consultation_generation
from app.ai.no_evidence import no_evidence_reply, unverified_web_risk_reply
from app.ai.provider import stream_chat
from app.ai.registry import get_model
from app.db.session import SessionLocal
from app.safety.triage import evaluate_triage

CASES = (
    ("red_flag_paraphrase", "说话突然含糊不清，半边身子使不上劲，几分钟后又好像正常了"),
    ("covered_dizziness", "头晕和眩晕有什么区别？"),
    ("covered_uti", "尿路感染的尿频尿急尿痛是什么？"),
    ("unfamiliar_disease", "法布雷病是什么？有哪些常见表现，什么情况需要就医？"),
    ("web_fallback_rare_disease", "庞贝病是什么？有哪些常见表现，什么情况需要就医？"),
)


async def main(case_id_filter: str | None = None) -> None:
    model = get_model("qwen3.8-flash")
    for case_id, question in CASES:
        if case_id_filter is not None and case_id != case_id_filter:
            continue
        start = perf_counter()
        triage = evaluate_triage(question)
        if triage.route == "emergency":
            result = {
                "case_id": case_id,
                "route": "emergency",
                "model_invoked": False,
                "elapsed_ms": round((perf_counter() - start) * 1000),
            }
            print(json.dumps(result, ensure_ascii=False), flush=True)
            continue

        async with SessionLocal() as db:
            try:
                graph = await run_consultation_generation(question, db)
                retrieval_items = graph["retrieval_items"]
                answer = no_evidence_reply(question, graph) or unverified_web_risk_reply(
                    question, graph
                )
                model_invoked = answer is None
                if answer is None:
                    answer = "".join(
                        [
                            chunk
                            async for chunk in stream_chat(
                                [{"role": "user", "content": question}],
                                model,
                                "plain",
                                render_rag_context(retrieval_items),
                            )
                        ]
                    )
                result = {
                    "case_id": case_id,
                    "route": graph["triage_route"],
                    "retrieval_status": graph["retrieval_status"],
                    "web_search_status": graph["web_search_status"],
                    "source_count": len(retrieval_items),
                    "source_trust_levels": [item["trust_level"] for item in retrieval_items],
                    "model_invoked": model_invoked,
                    "answer_chars": len(answer),
                    "has_safety_notice": "不作确诊" in answer,
                    "answer": answer,
                    "elapsed_ms": round((perf_counter() - start) * 1000),
                }
                print(json.dumps(result, ensure_ascii=False), flush=True)
            finally:
                await db.rollback()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", choices=[case_id for case_id, _ in CASES])
    parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="确认本次允许外部 embedding、搜索和聊天模型调用产生费用",
    )
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error("真实冒烟测试可能产生 API 费用，必须显式传入 --allow-paid")
    asyncio.run(main(args.case_id))
