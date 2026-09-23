"""Scheduled retention cleanup for encrypted medical image blobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Attachment, MessageAttachment
from app.services.audit_logs import AUDIT_OUTCOME_SUCCESS, add_audit_log
from app.services.image_deletion import (
    enqueue_image_deletion,
    process_image_deletion_jobs_best_effort,
    reconcile_orphaned_image_files,
)

_LOCK_ID = 6_214_831_908


@dataclass(frozen=True)
class ImageCleanupStats:
    expired: int
    orphaned: int
    lock_acquired: bool
    filesystem_orphans: int = 0
    deletion_completed: int = 0
    deletion_retrying: int = 0
    deletion_failed: int = 0


async def cleanup_medical_images(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> ImageCleanupStats:
    current = now or datetime.now(UTC)
    acquired = bool(
        await db.scalar(text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": _LOCK_ID})
    )
    if not acquired:
        await db.rollback()
        return ImageCleanupStats(expired=0, orphaned=0, lock_acquired=False)

    settings = get_settings()
    orphan_before = current - timedelta(hours=settings.image_orphan_hours)
    linked = exists(
        select(MessageAttachment.id).where(MessageAttachment.attachment_id == Attachment.id)
    )
    orphan_rows = (
        await db.scalars(
            select(Attachment)
            .where(
                Attachment.kind == "image",
                Attachment.image_storage_key.is_not(None),
                Attachment.created_at < orphan_before,
                ~linked,
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    orphan_ids = {row.id for row in orphan_rows}
    expired_rows = (
        await db.scalars(
            select(Attachment)
            .where(
                Attachment.kind == "image",
                Attachment.image_storage_key.is_not(None),
                Attachment.image_expires_at <= current,
                Attachment.id.not_in(orphan_ids) if orphan_ids else text("TRUE"),
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    stats = ImageCleanupStats(
        expired=len(expired_rows),
        orphaned=len(orphan_rows),
        lock_acquired=True,
    )
    if dry_run:
        await db.rollback()
        return stats

    for row in orphan_rows:
        if row.image_storage_key:
            await enqueue_image_deletion(
                db, row.image_storage_key, "UNBOUND_IMAGE_24H", now=current
            )
        await add_audit_log(
            db,
            actor_user_id=row.user_id,
            action="expire",
            resource_type="medical_image",
            resource_id=row.id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            reason_code="UNBOUND_IMAGE_24H",
        )
        await db.delete(row)
    for row in expired_rows:
        if row.image_storage_key:
            await enqueue_image_deletion(
                db, row.image_storage_key, "IMAGE_RETENTION_EXPIRED", now=current
            )
        row.image_storage_key = None
        row.image_key_ciphertext = None
        row.image_deleted_at = current
        await add_audit_log(
            db,
            actor_user_id=row.user_id,
            action="expire",
            resource_type="medical_image",
            resource_id=row.id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            reason_code="IMAGE_RETENTION_EXPIRED",
        )
    await db.commit()
    try:
        filesystem_orphans = await reconcile_orphaned_image_files(
            db,
            older_than=orphan_before,
            now=current,
        )
    except OSError:
        await db.rollback()
        filesystem_orphans = 0
    deletion = await process_image_deletion_jobs_best_effort(db, now=current)
    return ImageCleanupStats(
        expired=stats.expired,
        orphaned=stats.orphaned,
        lock_acquired=stats.lock_acquired,
        filesystem_orphans=filesystem_orphans,
        deletion_completed=deletion.completed,
        deletion_retrying=deletion.retrying,
        deletion_failed=deletion.failed,
    )
