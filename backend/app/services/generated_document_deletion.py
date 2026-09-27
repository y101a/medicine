"""Durable retryable deletion for encrypted generated document files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeneratedDocumentDeletionJob, GeneratedDocumentFile
from app.services.generated_document_storage import (
    list_generated_document_keys,
    remove_generated_document,
)

_RETRYABLE = ("pending", "retrying")


@dataclass(frozen=True)
class DocumentDeletionStats:
    completed: int = 0
    retrying: int = 0
    failed: int = 0


async def enqueue_document_deletion(
    db: AsyncSession,
    storage_key: str | None,
    reason: str,
    *,
    now: datetime | None = None,
) -> None:
    if not storage_key:
        return
    if not reason or len(reason) > 64:
        raise ValueError("Document deletion reason must be 1-64 characters")
    current = now or datetime.now(UTC)
    statement = (
        insert(GeneratedDocumentDeletionJob)
        .values(
            storage_key=storage_key,
            reason=reason,
            status="pending",
            attempt_count=0,
            next_attempt_at=current,
        )
        .on_conflict_do_update(
            index_elements=[GeneratedDocumentDeletionJob.storage_key],
            set_={
                "reason": reason,
                "status": "pending",
                "next_attempt_at": current,
                "last_error_code": None,
                "completed_at": None,
                "updated_at": current,
            },
            where=GeneratedDocumentDeletionJob.status == "completed",
        )
    )
    await db.execute(statement)


async def enqueue_document_deletions(
    db: AsyncSession,
    storage_keys: list[str],
    reason: str,
) -> None:
    current = datetime.now(UTC)
    for key in dict.fromkeys(storage_keys):
        await enqueue_document_deletion(db, key, reason, now=current)


async def process_document_deletion_jobs(
    db: AsyncSession,
    *,
    limit: int = 200,
    storage_keys: list[str] | None = None,
) -> DocumentDeletionStats:
    current = datetime.now(UTC)
    query = select(GeneratedDocumentDeletionJob).where(
        GeneratedDocumentDeletionJob.status.in_(_RETRYABLE),
        GeneratedDocumentDeletionJob.next_attempt_at <= current,
    )
    if storage_keys is not None:
        if not storage_keys:
            return DocumentDeletionStats()
        query = query.where(GeneratedDocumentDeletionJob.storage_key.in_(set(storage_keys)))
    jobs = (
        await db.scalars(
            query.order_by(GeneratedDocumentDeletionJob.next_attempt_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    completed = retrying = failed = 0
    for job in jobs:
        job.attempt_count += 1
        job.updated_at = current
        try:
            await remove_generated_document(job.storage_key)
        except ValueError:
            job.status = "failed"
            job.next_attempt_at = None
            job.last_error_code = "INVALID_STORAGE_KEY"
            failed += 1
        except OSError as exc:
            job.status = "retrying"
            delay = min(2 ** min(job.attempt_count, 16) * 60, 24 * 60 * 60)
            job.next_attempt_at = current + timedelta(seconds=delay)
            job.last_error_code = type(exc).__name__[:64]
            retrying += 1
        else:
            job.status = "completed"
            job.next_attempt_at = None
            job.last_error_code = None
            job.completed_at = current
            completed += 1
    await db.commit()
    return DocumentDeletionStats(completed=completed, retrying=retrying, failed=failed)


async def process_document_deletion_jobs_best_effort(
    db: AsyncSession,
    *,
    storage_keys: list[str] | None = None,
) -> DocumentDeletionStats:
    try:
        return await process_document_deletion_jobs(db, storage_keys=storage_keys)
    except SQLAlchemyError:
        await db.rollback()
        return DocumentDeletionStats()


async def reconcile_orphaned_generated_documents(
    db: AsyncSession,
    *,
    older_than: datetime,
    now: datetime | None = None,
) -> int:
    """Queue stale encrypted files that no generated-document row references."""
    candidates = await list_generated_document_keys(older_than)
    if not candidates:
        return 0
    live_keys = set(
        await db.scalars(
            select(GeneratedDocumentFile.storage_key).where(
                GeneratedDocumentFile.storage_key.in_(candidates)
            )
        )
    )
    orphaned = sorted(set(candidates) - live_keys)
    current = now or datetime.now(UTC)
    for key in orphaned:
        await enqueue_document_deletion(db, key, "FILESYSTEM_ORPHAN", now=current)
    await db.commit()
    return len(orphaned)
