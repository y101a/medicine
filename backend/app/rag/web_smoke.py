"""Run a generic-topic Tavily + pgvector smoke check without saving test rows.

Usage from backend/: python -m app.rag.web_smoke
Only a fixed disease name leaves the process. All test DB writes are rolled back.
External search/embedding calls can consume API quota.
"""

import asyncio

from sqlalchemy import select

from app.ai.graph.workflow import run_consultation_generation
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.retrieval import search_knowledge
from app.rag.web_search import SOURCE_KEY

TOPIC = "甲状腺结节"
QUESTION = f"{TOPIC}健康科普"


async def main() -> None:
    settings = get_settings()
    if settings.app_environment != "development":
        print("skipped: this check is development-only")
        return
    if not settings.tavily_api_key or not settings.tavily_api_key.get_secret_value().strip():
        print("skipped: Tavily key not configured")
        return

    async with SessionLocal() as db:
        try:
            first = await run_consultation_generation(QUESTION, db)
            print(
                "first:",
                f"local={first['retrieval_status']}",
                f"web={first['web_search_status']}",
                f"web_error={first['web_search_error_code'] or 'none'}",
                f"citations={len(first['retrieval_items'])}",
            )
            if first["web_search_status"] == "completed":
                await db.flush()
                cache = (
                    await db.execute(
                        select(KnowledgeDocument, KnowledgeChunk)
                        .join(KnowledgeSource, KnowledgeDocument.source_id == KnowledgeSource.id)
                        .join(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
                        .where(
                            KnowledgeSource.source_key == SOURCE_KEY,
                            KnowledgeDocument.canonical_url
                            == first["retrieval_items"][0]["canonical_url"],
                        )
                        .order_by(KnowledgeDocument.created_at.desc())
                        .limit(1)
                    )
                ).first()
                print(
                    "cache:",
                    f"saved={cache is not None}",
                    f"vector_ready={cache[1].embedding is not None if cache else False}",
                )
                if cache:
                    job = await db.scalar(
                        select(IngestionJob)
                        .where(IngestionJob.document_id == cache[0].id)
                        .order_by(IngestionJob.created_at.desc())
                        .limit(1)
                    )
                    print("embedding_job:", job.error_code or job.status if job else "missing")
                ranked = await search_knowledge(db, QUESTION, top_k=10)
                cached_scores = [
                    (index, item.similarity)
                    for index, item in enumerate(ranked.items, start=1)
                    if item.source_key == SOURCE_KEY
                    and item.canonical_url == first["retrieval_items"][0]["canonical_url"]
                ]
                print("cache_rank_similarity:", cached_scores or "not_in_top_10")
                second = await run_consultation_generation(QUESTION, db)
                reused = bool(
                    second["web_search_status"] == "skipped"
                    and any(
                        item["source_key"] == "web_search_prototype"
                        for item in second["retrieval_items"]
                    )
                )
                print(
                    "second:",
                    f"local={second['retrieval_status']}",
                    f"web={second['web_search_status']}",
                    "cached_prototype_reused=" + str(reused).lower(),
                )
            elif first["retrieval_status"] == "completed":
                print("second: skipped, topic already covered by local evidence")
            else:
                print("second: skipped, no eligible official-site excerpt to cache")
        finally:
            await db.rollback()
            print("database: rolled back; no smoke-test data persisted")


if __name__ == "__main__":
    asyncio.run(main())
