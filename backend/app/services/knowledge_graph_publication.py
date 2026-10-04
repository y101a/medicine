"""发布 outbox（G1：只做入队与租约状态机，**不含 Neo4j 写入**）。

分工与 plan 第 7.3 节一致：PostgreSQL 事务内登记「期望 revision」，worker 按 revision 幂等
投影；Neo4j 写入失败不回滚已审核事实，线上只使用「PG 期望 revision 与图当前 revision 一致」
的那一版图。G2 的 worker 只需要在 `claim_next_job` 与 `complete_job`/`fail_job` 之间插一段
写 Neo4j 的代码，不需要再动本模块的编排逻辑。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import (
    GraphClaim,
    GraphClaimStatus,
    GraphPublicationJob,
    GraphPublicationStatus,
)
from app.services.knowledge_graph_review import claims_ready_to_publish

#: 一个发布任务最多被尝试几次，超过就不再自动重试（留给人工看 error_code）。
MAX_PUBLICATION_ATTEMPTS = 3


class KnowledgeGraphPublicationError(ValueError):
    """发布编排失败：没有可发布的已审核关系、租约不归本 worker 等。"""


@dataclass(slots=True)
class PublicationResult:
    revision: int
    claim_count: int
    job_id: UUID
    idempotency_key: str


@dataclass(slots=True)
class ClaimedJob:
    job_id: UUID
    target_revision: int
    attempts: int


@dataclass(slots=True)
class PublicationStatusView:
    jobs_by_status: dict[str, int]
    expected_revision: int
    last_published_revision: int | None
    oldest_pending_revision: int | None


async def enqueue_publication(db: AsyncSession, *, actor: str) -> PublicationResult:
    """把当前所有「已审核 + 有效证据」的关系登记为一个新 revision。

    幂等：同一批关系已经发布过时，这里找不到新的可发布关系，直接报错而不是重复建任务。
    """

    reviewer = actor.strip()
    if not reviewer:
        raise KnowledgeGraphPublicationError("发布操作人不能为空")
    claims = await claims_ready_to_publish(db)
    if not claims:
        raise KnowledgeGraphPublicationError(
            "没有可发布的已审核关系：候选还没通过审核，或者证据已失效"
        )
    highest_claim_revision = max((claim.published_revision or 0 for claim in claims), default=0)
    highest_job_revision = (
        await db.scalar(select(func.max(GraphPublicationJob.target_revision)))
    ) or 0
    revision = max(highest_claim_revision, highest_job_revision) + 1
    published_at = datetime.now(UTC)
    for claim in claims:
        claim.status = GraphClaimStatus.PUBLISHED
        claim.published_revision = revision
        claim.published_at = published_at
    job = GraphPublicationJob(
        idempotency_key=f"graph-revision:{revision}",
        target_revision=revision,
        claim_count=len(claims),
        status=GraphPublicationStatus.QUEUED,
        attempts=0,
    )
    db.add(job)
    await db.flush()
    return PublicationResult(
        revision=revision,
        claim_count=len(claims),
        job_id=job.id,
        idempotency_key=job.idempotency_key,
    )


async def enqueue_snapshot_rebuild(db: AsyncSession, *, actor: str) -> PublicationResult | None:
    """撤回、改名、来源失效后为完整当前图追加 revision；允许空图。"""

    if not actor.strip():
        raise KnowledgeGraphPublicationError("发布操作人不能为空")
    highest_job = (await db.scalar(select(func.max(GraphPublicationJob.target_revision)))) or 0
    if not highest_job:
        return None  # 从未发布，无旧图需要清理。
    count = (
        await db.scalar(
            select(func.count()).select_from(GraphClaim).where(
                GraphClaim.status == GraphClaimStatus.PUBLISHED
            )
        )
    ) or 0
    revision = int(highest_job) + 1
    job = GraphPublicationJob(
        idempotency_key=f"graph-revision:{revision}",
        target_revision=revision,
        claim_count=int(count),
        status=GraphPublicationStatus.QUEUED,
        attempts=0,
    )
    db.add(job)
    await db.flush()
    return PublicationResult(revision, int(count), job.id, job.idempotency_key)


async def claim_next_job(
    db: AsyncSession, *, owner: str, lease_seconds: int = 300
) -> ClaimedJob | None:
    """取一个可跑的任务并加租约（`FOR UPDATE SKIP LOCKED`，多个 worker 不会抢同一条）。

可跑 = 排队中 / 租约过期的运行中 / **失败但没超过重试上限**。失败留在队列里是有意的：
Neo4j 临时不可用属于可恢复故障，人工不必重新入队；超过 `MAX_PUBLICATION_ATTEMPTS`
后就停手，等人工看 `error_code` 处理。
"""

    worker = owner.strip()
    if not worker:
        raise KnowledgeGraphPublicationError("worker 标识不能为空")
    if lease_seconds <= 0:
        raise KnowledgeGraphPublicationError("租约秒数必须为正")
    now = datetime.now(UTC)
    job = await db.scalar(
        select(GraphPublicationJob)
        .where(
            GraphPublicationJob.status.in_(
                [
                    GraphPublicationStatus.QUEUED,
                    GraphPublicationStatus.RUNNING,
                    GraphPublicationStatus.FAILED,
                ]
            ),
            GraphPublicationJob.attempts < MAX_PUBLICATION_ATTEMPTS,
            (GraphPublicationJob.lease_expires_at.is_(None))
            | (GraphPublicationJob.lease_expires_at < now),
        )
        .order_by(GraphPublicationJob.target_revision)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = GraphPublicationStatus.RUNNING
    job.attempts += 1
    job.lease_owner = worker
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.error_code = None
    await db.flush()
    return ClaimedJob(job_id=job.id, target_revision=job.target_revision, attempts=job.attempts)


async def complete_job(db: AsyncSession, job_id: UUID, *, owner: str) -> None:
    """投影成功后回写成功 revision。"""

    job = await _get_job(db, job_id)
    _require_lease_owner(job, owner)
    job.status = GraphPublicationStatus.SUCCEEDED
    job.finished_at = datetime.now(UTC)
    job.lease_owner = None
    job.lease_expires_at = None
    await db.flush()


async def fail_job(
    db: AsyncSession, job_id: UUID, *, owner: str, error_code: str, error_message: str
) -> None:
    """投影失败：记错误码与信息，**不回滚已审核事实**，等下一次重试或人工处理。"""

    job = await _get_job(db, job_id)
    _require_lease_owner(job, owner)
    job.status = GraphPublicationStatus.FAILED
    job.finished_at = datetime.now(UTC)
    job.error_code = error_code.strip()[:64] or "GRAPH_PUBLICATION_FAILED"
    job.error_message = error_message.strip()[:2000] or None
    job.lease_owner = None
    job.lease_expires_at = None
    await db.flush()


async def publication_status(db: AsyncSession) -> PublicationStatusView:
    jobs = list((await db.scalars(select(GraphPublicationJob))).all())
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    expected_revision = max((job.target_revision for job in jobs), default=0)
    succeeded = [
        job.target_revision
        for job in jobs
        if job.status == GraphPublicationStatus.SUCCEEDED
    ]
    pending = [
        job.target_revision
        for job in jobs
        if job.status in (GraphPublicationStatus.QUEUED, GraphPublicationStatus.RUNNING)
    ]
    return PublicationStatusView(
        jobs_by_status=counts,
        expected_revision=int(expected_revision),
        last_published_revision=max(succeeded) if succeeded else None,
        oldest_pending_revision=min(pending) if pending else None,
    )


def _require_lease_owner(job: GraphPublicationJob, owner: str) -> None:
    worker = owner.strip()
    if not worker:
        raise KnowledgeGraphPublicationError("worker 标识不能为空")
    if job.lease_owner != worker:
        raise KnowledgeGraphPublicationError(
            f"任务 {job.id} 的租约不属于 {worker}（当前：{job.lease_owner or '无'}）"
        )


async def _get_job(db: AsyncSession, job_id: UUID) -> GraphPublicationJob:
    job = await db.get(GraphPublicationJob, job_id)
    if job is None:
        raise KnowledgeGraphPublicationError(f"发布任务不存在：{job_id}")
    return job
