"""一次处理一个图谱 outbox 任务；可由计划任务循环调用。"""

import argparse
import asyncio
import os

from app.db.session import SessionLocal
from app.services.knowledge_graph_neo4j import project_snapshot
from app.services.knowledge_graph_publication import claim_next_job, complete_job, fail_job
from app.services.knowledge_graph_snapshot import build_snapshot


async def run_once(*, driver, owner: str, database: str = "neo4j") -> bool:
    async with SessionLocal() as db:
        job = await claim_next_job(db, owner=owner)
        await db.commit()
    if job is None:
        return False
    try:
        async with SessionLocal() as db:
            # 取一致的 PostgreSQL 读快照；PG 是唯一事实源。
            async with db.begin():
                snapshot = await build_snapshot(db, revision=job.target_revision)
        await asyncio.to_thread(project_snapshot, driver, snapshot, database=database)
        async with SessionLocal() as db:
            await complete_job(db, job.job_id, owner=owner)
            await db.commit()
    except Exception as exc:
        async with SessionLocal() as db:
            await fail_job(
                db, job.job_id, owner=owner,
                error_code="NEO4J_PROJECTION_FAILED", error_message=str(exc),
            )
            await db.commit()
        raise
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="公共医学图谱全量快照投影 worker")
    parser.add_argument("--owner", default="neo4j-worker")
    args = parser.parse_args()
    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    if not uri or not username or not password:
        parser.error("必须设置 NEO4J_URI、NEO4J_USERNAME、NEO4J_PASSWORD")
    try:
        from neo4j import GraphDatabase
    except ImportError:
        parser.error("缺少可选依赖 neo4j；先取得安装许可再安装 backend[neo4j]")
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        driver.verify_connectivity()
        ran = asyncio.run(
            run_once(
                driver=driver,
                owner=args.owner,
                database=os.environ.get("NEO4J_DATABASE", "neo4j"),
            )
        )
        print("projected" if ran else "no-job")


if __name__ == "__main__":
    main()
