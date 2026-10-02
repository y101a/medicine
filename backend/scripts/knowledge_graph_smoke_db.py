"""知识图谱治理冒烟用的临时库工具（建库/造数据/制造正文漂移/删库）。

它**只操作 `kg_cli_smoke` 这个一次性数据库**：dev 库 `medical_assistant` 不会被写入。
配套脚本：`backend/scripts/run_knowledge_graph_smoke.ps1`。
"""

import asyncio
import sys
from datetime import UTC, datetime

import asyncpg

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource

SMOKE_DB = "kg_cli_smoke"
GRAPH_TABLES = [
    "graph_concepts",
    "graph_concept_aliases",
    "graph_claims",
    "graph_claim_evidence",
    "graph_publication_jobs",
]
CHUNKS = [
    "肺癌的常见表现包括咳嗽、咯血和胸痛。出现咯血应尽快到胸外科就诊。戒烟是最重要的自我照护措施。",
    "本页内容正在整理中。",
]


async def _admin_connection(database: str = "postgres") -> asyncpg.Connection:
    settings = get_settings()
    return await asyncpg.connect(
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=database,
        host=settings.postgres_host,
        port=settings.postgres_port,
    )


async def create() -> None:
    """建临时库并装扩展（容器 init 只给 dev 库装了扩展，迁移本身不装）。"""

    connection = await _admin_connection()
    try:
        await connection.execute(f"DROP DATABASE IF EXISTS {SMOKE_DB} WITH (FORCE)")
        await connection.execute(f"CREATE DATABASE {SMOKE_DB}")
    finally:
        await connection.close()
    smoke = await _admin_connection(SMOKE_DB)
    try:
        for extension in ("vector", "pg_trgm"):
            await smoke.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    finally:
        await smoke.close()
    print("smoke db ready")


async def seed() -> None:
    """造一篇已审核公共文档与两个知识块（采集链本身属于 Codex，这里只准备输入）。"""

    async with SessionLocal() as db:
        now = datetime.now(UTC)
        source = KnowledgeSource(
            source_key="kg-smoke-source",
            priority=1,
            organization="冒烟测试机构",
            channel_name="冒烟渠道",
            authority_level="test_authority",
            jurisdiction="CN",
            language="zh-CN",
            entry_url="https://www.nhc.gov.cn/test/kg-smoke.shtml",
            ingestion_status="approved",
            automated_collection=False,
        )
        db.add(source)
        await db.flush()
        document = KnowledgeDocument(
            source_id=source.id,
            canonical_url="https://www.nhc.gov.cn/test/kg-smoke.shtml",
            title="冒烟测试：肺癌科普",
            content_type="markdown",
            language="zh-CN",
            jurisdiction="CN",
            published_at=now,
            version_label="smoke-v1",
            review_status="approved",
            license_type="test_permission",
            legal_reviewed_at=now,
            legal_reviewed_by="版权测试员",
            medical_reviewed_at=now,
            medical_reviewed_by="医学测试员",
            content_hash="a" * 64,
            content_text="\n".join(CHUNKS),
        )
        db.add(document)
        await db.flush()
        for index, text in enumerate(CHUNKS):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=index,
                    section_title=f"第 {index} 节",
                    content=text,
                    content_hash=f"{index:064d}",
                )
            )
        await db.flush()
        document_id = document.id
        await db.commit()
    print(document_id)


async def drift() -> None:
    """改掉第一个知识块的正文哈希，模拟「来源正文变了但证据还挂在旧哈希上」。"""

    from sqlalchemy import select

    async with SessionLocal() as db:
        chunk = await db.scalar(
            select(KnowledgeChunk).where(KnowledgeChunk.chunk_index == 0).limit(1)
        )
        chunk.content_hash = "f" * 64
        await db.commit()
    print("drifted")


async def drop() -> None:
    """删临时库，并确认**真实开发库**里的图谱表没有被写入。"""

    connection = await _admin_connection()
    try:
        await connection.execute(f"DROP DATABASE IF EXISTS {SMOKE_DB} WITH (FORCE)")
    finally:
        await connection.close()
    settings = get_settings()
    dev = await _admin_connection(settings.postgres_db)
    try:
        head = await dev.fetchval("select version_num from alembic_version")
        print(f"dev db {settings.postgres_db} alembic head: {head}")
        for table in GRAPH_TABLES:
            count = await dev.fetchval("select count(*) from " + table)
            print(f"  {table}: {count} rows")
    finally:
        await dev.close()


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "create":
        asyncio.run(create())
    elif action == "seed":
        asyncio.run(seed())
    elif action == "drift":
        asyncio.run(drift())
    elif action == "drop":
        asyncio.run(drop())
    else:  # pragma: no cover
        raise SystemExit(f"unknown action: {action}")