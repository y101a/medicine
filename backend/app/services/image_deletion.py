"""Durable, retryable deletion for encrypted medical image blobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, ImageDeletionJob
from app.services.medical_image_storage import (
    list_stored_image_keys,
    remove_image,
)

_RETRYABLE_STATUSES = ("pending", "retrying")
_MAX_BACKOFF_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ImageDeletionStats:
    completed: int = 0
    retrying: int = 0
    failed: int = 0


async def enqueue_image_deletion(
    db: AsyncSession,
    storage_key: str | None,
    reason: str,
    *,
    now: datetime | None = None,
) -> None:
    """Persist deletion intent in the caller's current database transaction."""
    if not storage_key:
        return
    if not reason or len(reason) > 64:
        raise ValueError("Image deletion reason must be 1-64 characters")
    current = now or datetime.now(UTC)
    statement = (
        insert(ImageDeletionJob)
        .values(
            storage_key=storage_key,
            reason=reason,
            status="pending",
            attempt_count=0,
            next_attempt_at=current,
        )
        .on_conflict_do_update(
            index_elements=[ImageDeletionJob.storage_key],
            set_={
                "reason": reason,
                "status": "pending",
                "next_attempt_at": current,
                "last_error_code": None,
                "completed_at": None,
                "updated_at": current,
            },
            where=ImageDeletionJob.status == "completed",
        )
    )
    await db.execute(statement)


async def enqueue_image_deletions(
    db: AsyncSession,
    storage_keys: list[str],
    reason: str,
    *,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(UTC)
    for storage_key in dict.fromkeys(storage_keys):
        await enqueue_image_deletion(db, storage_key, reason, now=current)


def _retry_at(current: datetime, attempt_count: int) -> datetime:
    delay = min(2 ** min(attempt_count, 16) * 60, _MAX_BACKOFF_SECONDS)
    return current + timedelta(seconds=delay)


async def process_image_deletion_jobs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 200,
    storage_keys: list[str] | None = None,
) -> ImageDeletionStats:
    """Claim due jobs, delete idempotently, and persist retry state."""
    current = now or datetime.now(UTC)
    query = select(ImageDeletionJob).where(
        ImageDeletionJob.status.in_(_RETRYABLE_STATUSES),
        ImageDeletionJob.next_attempt_at <= current,
    )
    if storage_keys is not None:
        if not storage_keys:
            return ImageDeletionStats()
        query = query.where(ImageDeletionJob.storage_key.in_(set(storage_keys)))
    jobs = (
        await db.scalars(
            query.order_by(
                ImageDeletionJob.next_attempt_at.asc(),
                ImageDeletionJob.created_at.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()

    completed = retrying = failed = 0
    for job in jobs:
        job.attempt_count += 1
        job.updated_at = current
        try:
            await remove_image(job.storage_key)
        except ValueError:
            job.status = "failed"
            job.next_attempt_at = None
            job.last_error_code = "INVALID_STORAGE_KEY"
            failed += 1
        except OSError as exc:
            job.status = "retrying"
            job.next_attempt_at = _retry_at(current, job.attempt_count)
            job.last_error_code = type(exc).__name__[:64]
            retrying += 1
        else:
            job.status = "completed"
            job.next_attempt_at = None
            job.last_error_code = None
            job.completed_at = current
            completed += 1
    await db.commit()
    return ImageDeletionStats(completed=completed, retrying=retrying, failed=failed)


async def process_image_deletion_jobs_best_effort(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 200,
    storage_keys: list[str] | None = None,
) -> ImageDeletionStats:
    """Do not turn a committed logical deletion into an API failure."""
    try:
        return await process_image_deletion_jobs(
            db,
            now=now,
            limit=limit,
            storage_keys=storage_keys,
        )
    except SQLAlchemyError:
        await db.rollback()
        return ImageDeletionStats()


async def discard_untracked_image(storage_key: str | None) -> None:
    """Delete a blob from a failed upload, persisting a retry if unlink fails."""
    if not storage_key:
        return
    try:
        await remove_image(storage_key)
        return
    except (OSError, ValueError):
        pass

    from app.db.session import SessionLocal

    try:
        async with SessionLocal() as db:
            await enqueue_image_deletion(db, storage_key, "UPLOAD_ROLLBACK")
            await db.commit()
    except SQLAlchemyError:
        # A later filesystem reconciliation can still discover the untracked blob.
        return


async def reconcile_orphaned_image_files(
    db: AsyncSession,
    *,
    older_than: datetime,
    now: datetime | None = None,
) -> int:
    """Queue stale blobs/temp files that have no live attachment row."""
    current = now or datetime.now(UTC)
    candidates = await list_stored_image_keys(older_than)
    if not candidates:
        return 0
    live_keys = set(
        await db.scalars(
            select(Attachment.image_storage_key).where(Attachment.image_storage_key.in_(candidates))
        )
    )
    orphaned = sorted(set(candidates) - live_keys)
    await enqueue_image_deletions(
        db,
        orphaned,
        "FILESYSTEM_ORPHAN",
        now=current,
    )
    await db.commit()
    return len(orphaned)
