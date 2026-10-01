"""Database-shared speech quotas and per-message concurrency control."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AuditLog


def _lock_key(value: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )


async def enforce_speech_limits(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    now: datetime | None = None,
) -> None:
    message_lock = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
        {"lock_id": _lock_key(f"speech-message:{user_id}:{message_id}")},
    )
    if not message_lock:
        raise AppError(409, "SPEECH_MESSAGE_BUSY", "这条回答正在生成语音，请稍候")

    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": _lock_key(f"speech-user:{user_id}")},
    )
    current = now or datetime.now(UTC)
    day_start = datetime.combine(current.date(), time.min, tzinfo=UTC)
    filters = (
        AuditLog.actor_user_id == user_id,
        AuditLog.action == "synthesize",
        AuditLog.resource_type == "voice_output",
    )
    ten_minutes = await db.scalar(
        select(func.count(AuditLog.id)).where(
            *filters,
            AuditLog.created_at >= current - timedelta(minutes=10),
        )
    )
    today = await db.scalar(
        select(func.count(AuditLog.id)).where(
            *filters,
            AuditLog.created_at >= day_start,
        )
    )
    settings = get_settings()
    if (ten_minutes or 0) >= settings.tts_limit_10m or (
        today or 0
    ) >= settings.tts_limit_daily:
        raise AppError(429, "SPEECH_RATE_LIMITED", "语音生成过于频繁，请稍后再试")
