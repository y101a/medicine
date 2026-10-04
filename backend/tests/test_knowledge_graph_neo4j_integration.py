"""显式配置 NEO4J_* 时运行的真实数据库投影冒烟。"""

import os
from uuid import UUID

import pytest
from test_knowledge_graph_review_publish import approve_all_candidates, extracted_fixture

from app import knowledge_graph_worker
from app.models.knowledge_graph import GraphPublicationJob, GraphPublicationStatus
from app.services.knowledge_graph_neo4j import project_snapshot
from app.services.knowledge_graph_publication import enqueue_publication, publication_status
from app.services.knowledge_graph_review import retire_claim
from app.services.knowledge_graph_snapshot import GraphSnapshot, build_snapshot


@pytest.mark.asyncio
async def test_real_neo4j_full_snapshot_rebuild(profile_context, monkeypatch):
    uri = os.environ.get("NEO4J_URI")
    password = os.environ.get("NEO4J_PASSWORD")
    if not uri or not password or os.environ.get("NEO4J_TEST_ALLOW_RESET") != "1":
        pytest.skip("真实 Neo4j 联调需要连接配置及 NEO4J_TEST_ALLOW_RESET=1")
    from neo4j import GraphDatabase

    _, db, _ = profile_context
    await extracted_fixture(db)
    await approve_all_candidates(db)
    first = await enqueue_publication(db, actor="医学测试员")
    snapshot1 = await build_snapshot(db, revision=first.revision)
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    class SharedSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(knowledge_graph_worker, "SessionLocal", SharedSession)
    with GraphDatabase.driver(
        uri, auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), password)
    ) as driver:
        driver.verify_connectivity()
        # 只在显式测试开关下清除该测试容器此前留下的公共图投影。
        with driver.session(database=database) as session:
            session.run("MATCH (n:PublicMedicalGraph) DETACH DELETE n").consume()
        assert await knowledge_graph_worker.run_once(
            driver=driver, owner="integration-worker", database=database
        )
        published_job = await db.get(GraphPublicationJob, first.job_id)
        assert published_job.status == GraphPublicationStatus.SUCCEEDED
        with driver.session(database=database) as session:
            row = session.run(
                "MATCH (m:PublicGraphMeta {id: $id}) RETURN m.revision AS revision, "
                "m.claim_count AS claims, m.evidence_count AS evidence",
                id="public-medical",
            ).single()
            assert row["revision"] == 1
            assert row["claims"] == 5
            assert row["evidence"] >= 5
            assert session.run(
                "MATCH (n:PublicMedicalGraph) WHERE n.user_id IS NOT NULL "
                "OR n.patient_id IS NOT NULL RETURN count(n) AS count"
            ).single()["count"] == 0

        await retire_claim(
            db, UUID(snapshot1.claims[0]["id"]), reviewer="医学测试员", reason="联调撤回"
        )
        revision2 = (await publication_status(db)).expected_revision
        assert await knowledge_graph_worker.run_once(
            driver=driver, owner="integration-worker", database=database
        )
        with driver.session(database=database) as session:
            assert session.run("MATCH (c:PublicClaim) RETURN count(c) AS count").single()[
                "count"
            ] == 4
            assert session.run(
                "MATCH (c:PublicClaim {id: $id}) RETURN count(c) AS count",
                id=snapshot1.claims[0]["id"],
            ).single()["count"] == 0

        from app.services.knowledge_graph_publication import enqueue_snapshot_rebuild

        failed_job = await enqueue_snapshot_rebuild(db, actor="故障测试")

        class BrokenDriver:
            def session(self, **_):
                raise RuntimeError("synthetic Neo4j outage")

        with pytest.raises(RuntimeError, match="synthetic Neo4j outage"):
            await knowledge_graph_worker.run_once(
                driver=BrokenDriver(), owner="integration-worker", database=database
            )
        stored_job = await db.get(GraphPublicationJob, failed_job.job_id)
        await db.refresh(stored_job)
        assert stored_job.status == GraphPublicationStatus.FAILED
        assert await knowledge_graph_worker.run_once(
            driver=driver, owner="integration-worker", database=database
        )
        await db.refresh(stored_job)
        assert stored_job.status == GraphPublicationStatus.SUCCEEDED

        project_snapshot(driver, GraphSnapshot(revision2 + 2, [], [], []), database=database)
        with driver.session(database=database) as session:
            assert session.run("MATCH (n:PublicMedicalGraph) RETURN count(n) AS count").single()[
                "count"
            ] == 1  # 仅保留 revision 元数据，旧事实全部清空。
            session.run("MATCH (n:PublicMedicalGraph) DETACH DELETE n").consume()
