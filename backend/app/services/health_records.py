"""Health record storage and retrieval.

Boundary: only facts the user stated themselves are stored. Model output is treated as
a restatement of the user's own words, and record data never feeds red-flag triage.
"""

import asyncio
import hashlib
import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.health_context import render_health_context
from app.ai.health_eligibility import evaluate_health_extraction_eligibility
from app.ai.health_extract import extract_health_facts, is_safe_fact
from app.ai.registry import ModelConfig
from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.db.session import SessionLocal
from app.models import (
    Consultation,
    HealthRecord,
    HealthRecordCategory,
    HealthRecordSettings,
    HealthRecordSource,
    Message,
)
from app.models.health_record import CATEGORY_LABELS, ONBOARDING_STATUS_LABELS
from app.schemas.health_records import (
    HealthRecordCreate,
    HealthRecordList,
    HealthRecordOnboarding,
    HealthRecordOut,
    HealthRecordSettingsOut,
    HealthRecordSettingsUpdate,
    HealthRecordUpdate,
)
from app.services.model_credentials import preferred_model_for_user

MAX_LIST_ITEMS = 200
MAX_CONTEXT_RECORDS = 20
MAX_CONTEXT_CHARS = 1200
MAX_CONCURRENT_EXTRACTIONS = 4

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    """Observable result of one extraction attempt.

    ``reason`` carries a controlled code (eligibility reason, ``collection-disabled``,
    ``already-extracted``, ``no-model``, or the AppError code). Neither the health text
    nor any credential is ever logged or returned.
    """

    status: Literal["stored", "skipped", "failed"]
    stored: int = 0
    reason: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {"stored": self.stored, "status": self.status, "reason": self.reason}


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def content_hash(value: str) -> str:
    return hashlib.sha256(_normalized(value).casefold().encode("utf-8")).hexdigest()


def record_out(row: HealthRecord) -> HealthRecordOut:
    return HealthRecordOut(
        id=row.id,
        category=row.category,
        category_label=CATEGORY_LABELS[row.category],
        content=decrypt_sensitive(row.content_ciphertext),
        source=row.source,
        recorded_at=row.recorded_at,
        updated_at=row.updated_at,
    )


async def _settings_row(db: AsyncSession, user_id: UUID) -> HealthRecordSettings | None:
    return await db.scalar(
        select(HealthRecordSettings).where(HealthRecordSettings.user_id == user_id)
    )


async def get_or_create_settings(db: AsyncSession, user_id: UUID) -> HealthRecordSettings:
    row = await _settings_row(db, user_id)
    if row is None:
        row = HealthRecordSettings(user_id=user_id)
        db.add(row)
        await db.flush()
    return row


async def _record_count(db: AsyncSession, user_id: UUID) -> int:
    total = await db.scalar(
        select(func.count()).select_from(HealthRecord).where(HealthRecord.user_id == user_id)
    )
    return int(total or 0)


async def settings_out(db: AsyncSession, user_id: UUID) -> HealthRecordSettingsOut:
    """Read-only view: a missing row means the confirmed default (collecting,未通知)."""

    row = await _settings_row(db, user_id)
    return HealthRecordSettingsOut(
        collection_enabled=row.collection_enabled if row else True,
        notice_seen=row.notice_seen_at is not None if row else False,
        record_count=await _record_count(db, user_id),
    )


async def update_settings(
    db: AsyncSession, user_id: UUID, payload: HealthRecordSettingsUpdate
) -> HealthRecordSettingsOut:
    row = await get_or_create_settings(db, user_id)
    if payload.collection_enabled is not None:
        row.collection_enabled = payload.collection_enabled
    if payload.notice_seen is not None:
        row.notice_seen_at = datetime.now(UTC) if payload.notice_seen else None
    await db.commit()
    return await settings_out(db, user_id)


async def list_records(
    db: AsyncSession, user_id: UUID, limit: int = MAX_LIST_ITEMS
) -> HealthRecordList:
    rows = await db.scalars(
        select(HealthRecord)
        .where(HealthRecord.user_id == user_id)
        .order_by(HealthRecord.recorded_at.desc(), HealthRecord.id.desc())
        .limit(min(limit, MAX_LIST_ITEMS))
    )
    return HealthRecordList(items=[record_out(row) for row in rows])


async def _upsert_fact(
    db: AsyncSession,
    user_id: UUID,
    category: HealthRecordCategory,
    content: str,
    source: HealthRecordSource,
    message_id: UUID | None = None,
) -> bool:
    """Store one fact; returns False when the same fact is already recorded."""

    # 只做 strip：NFKC 仅用于去重哈希，避免改写用户原文的全角标点。
    clean = content.strip()[:500]
    if not clean:
        return False
    # 双保险：对话提取的内容即使绕过提取层，推断性表述也不会落库。
    if source is HealthRecordSource.CONVERSATION and not is_safe_fact(clean):
        return False
    result = await db.execute(
        insert(HealthRecord)
        .values(
            id=uuid4(),
            user_id=user_id,
            category=category,
            content_ciphertext=encrypt_sensitive(clean),
            content_hash=content_hash(clean),
            source=source,
            source_message_id=message_id,
            # 用 Python 侧时间戳：server_default 的 now() 在同一事务内是常量，
            # 同批写入的记录会时间相同、排序退化。
            recorded_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_health_records_user_category_hash")
    )
    return bool(result.rowcount)


async def _find_fact(
    db: AsyncSession, user_id: UUID, category: HealthRecordCategory, content: str
) -> HealthRecord | None:
    return await db.scalar(
        select(HealthRecord).where(
            HealthRecord.user_id == user_id,
            HealthRecord.category == category,
            HealthRecord.content_hash == content_hash(content),
        )
    )


async def create_record(
    db: AsyncSession, user_id: UUID, payload: HealthRecordCreate
) -> HealthRecordOut:
    await _upsert_fact(db, user_id, payload.category, payload.content, HealthRecordSource.USER)
    row = await _find_fact(db, user_id, payload.category, payload.content)
    await db.commit()
    if row is None:
        raise AppError(409, "HEALTH_RECORD_CONFLICT", "健康记录保存冲突，请重试")
    return record_out(row)


async def owned_record(db: AsyncSession, user_id: UUID, record_id: UUID) -> HealthRecord:
    row = await db.scalar(
        select(HealthRecord)
        .where(HealthRecord.id == record_id, HealthRecord.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "HEALTH_RECORD_NOT_FOUND", "健康记录不存在或无权访问")
    return row


async def update_record(
    db: AsyncSession, user_id: UUID, record_id: UUID, payload: HealthRecordUpdate
) -> HealthRecordOut:
    row = await owned_record(db, user_id, record_id)
    if payload.content is not None:
        # 同样只 strip：NFKC 只用于哈希，不能改写用户自己写的标点。
        row.content_ciphertext = encrypt_sensitive(payload.content.strip()[:500])
        row.content_hash = content_hash(payload.content)
    if payload.category is not None:
        row.category = payload.category
    # A hand-edited fact is a user-stated fact from now on.
    row.source = HealthRecordSource.USER
    row.recorded_at = datetime.now(UTC)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(409, "HEALTH_RECORD_CONFLICT", "该记录与已有记录重复") from exc
    # updated_at 由 onupdate 在数据库端生成，提交后该属性已过期，必须重新读取。
    await db.refresh(row)
    return record_out(row)


async def delete_record(db: AsyncSession, user_id: UUID, record_id: UUID) -> None:
    row = await owned_record(db, user_id, record_id)
    await db.delete(row)
    await db.commit()


async def record_onboarding(
    db: AsyncSession, user_id: UUID, payload: HealthRecordOnboarding
) -> HealthRecordSettingsOut:
    row = await get_or_create_settings(db, user_id)
    if row.notice_seen_at is None:
        row.notice_seen_at = datetime.now(UTC)
    label = ONBOARDING_STATUS_LABELS[payload.status]
    content = f"{label}：{payload.note}" if payload.note else label
    await _upsert_fact(
        db, user_id, HealthRecordCategory.GENERAL_STATUS, content, HealthRecordSource.ONBOARDING
    )
    await db.commit()
    return await settings_out(db, user_id)


async def build_health_context(db: AsyncSession, user_id: UUID) -> str | None:
    """Return the injection block, or None when there is nothing to inject.

    When the user turns collection off, existing records are also kept out of the
    answer prompt; they stay visible in the health record page until deleted.
    """

    row = await _settings_row(db, user_id)
    if row is not None and not row.collection_enabled:
        return None
    rows = await db.scalars(
        select(HealthRecord)
        .where(HealthRecord.user_id == user_id)
        .order_by(HealthRecord.recorded_at.desc(), HealthRecord.id.desc())
        .limit(MAX_CONTEXT_RECORDS)
    )
    entries: list[dict[str, str]] = []
    total = 0
    for item in rows:
        entry = {
            "category": CATEGORY_LABELS[item.category],
            "content": decrypt_sensitive(item.content_ciphertext),
            "recordedAt": item.recorded_at.date().isoformat(),
        }
        encoded = json.dumps(entry, ensure_ascii=False)
        if total + len(encoded) > MAX_CONTEXT_CHARS:
            break
        total += len(encoded)
        entries.append(entry)
    if not entries:
        return None
    return render_health_context(json.dumps(entries, ensure_ascii=False))


async def extraction_model(db: AsyncSession, user_id: UUID) -> ModelConfig | None:
    return await preferred_model_for_user(db, user_id)


async def _existing_fact_texts(db: AsyncSession, user_id: UUID, limit: int = 20) -> list[str]:
    rows = await db.scalars(
        select(HealthRecord)
        .where(HealthRecord.user_id == user_id)
        .order_by(HealthRecord.recorded_at.desc())
        .limit(limit)
    )
    return [decrypt_sensitive(row.content_ciphertext) for row in rows]


async def extract_and_store(
    db: AsyncSession, user_id: UUID, user_text: str, message_id: UUID
) -> ExtractionOutcome:
    """Best-effort extraction of one user message; never raises so chat cannot break.

    资格判定只看**这条用户消息本身**（`app.ai.health_eligibility`），不复用 RAG 的
    `medical_content` 门控：那个门控回答的是“要不要检索医学知识”，会把「我最近总口渴」
    「脸上红红的」这类真实自述判成非医疗内容，于是采集开着也什么都存不下来。
    """

    row = await get_or_create_settings(db, user_id)
    if not row.collection_enabled:
        return ExtractionOutcome("skipped", reason="collection-disabled")
    if row.last_extracted_message_id == message_id:
        return ExtractionOutcome("skipped", reason="already-extracted")
    decision = evaluate_health_extraction_eligibility(user_text)
    if not decision.eligible:
        logger.info(
            "health_record_extraction_skipped code=ineligible reason=%s message_id=%s",
            decision.reason,
            message_id,
        )
        return ExtractionOutcome("skipped", reason=decision.reason)
    # `last_extracted_message_id` 只记得最近一条：重触发**较早**的消息时它会失配，
    # 于是白跑一次模型调用（记录靠 content_hash 兜住，但幂等不成立）。记录上的
    # `source_message_id` 是持久证据，两者合起来才算真的“这条消息已处理过”。
    stored_before = await db.scalar(
        select(func.count())
        .select_from(HealthRecord)
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.source_message_id == message_id,
        )
    )
    if stored_before:
        return ExtractionOutcome("skipped", reason="already-extracted")
    model = await extraction_model(db, user_id)
    if model is None:
        logger.warning("health_record_extraction_failed code=no-model message_id=%s", message_id)
        return ExtractionOutcome("failed", reason="no-model")
    try:
        facts = await extract_health_facts(
            user_text, model, existing_facts=await _existing_fact_texts(db, user_id)
        )
    except AppError as exc:
        logger.warning(
            "health_record_extraction_failed code=%s message_id=%s", exc.code, message_id
        )
        return ExtractionOutcome("failed", reason=exc.code)
    except Exception as exc:  # noqa: BLE001 - best effort, report only the type, never content
        logger.warning(
            "health_record_extraction_failed code=unexpected error_type=%s message_id=%s",
            type(exc).__name__,
            message_id,
        )
        return ExtractionOutcome("failed", reason="unexpected")
    stored = 0
    for fact in facts:
        created = await _upsert_fact(
            db,
            user_id,
            fact.category,
            fact.content,
            HealthRecordSource.CONVERSATION,
            message_id,
        )
        stored += 1 if created else 0
    row.last_extracted_message_id = message_id
    await db.commit()
    logger.info("health_record_extraction_stored stored=%d message_id=%s", stored, message_id)
    return ExtractionOutcome("stored", stored=stored)


async def extract_from_message(
    db: AsyncSession, user_id: UUID, consultation_id: UUID, message_id: UUID
) -> ExtractionOutcome:
    """message_id 是助手回答；抽取文本取它之前最近的一条用户消息。

    助手消息只用来**定位**对应的用户提问。是否值得抽取由那条用户消息本身的资格判定
    决定（`app.ai.health_eligibility`），与 `messages.is_medical_content` 无关——该标记
    由检索门控写入，用于决定要不要检索知识，不是“用户是否陈述了个人健康事实”。
    """

    answer = await db.scalar(
        select(Message)
        .join(Consultation, Consultation.id == Message.consultation_id)
        .where(
            Message.id == message_id,
            Message.consultation_id == consultation_id,
            Consultation.user_id == user_id,
        )
    )
    if answer is None or answer.role != "assistant":
        raise AppError(404, "HEALTH_EXTRACT_SOURCE_NOT_FOUND", "找不到可用于更新的助手回答")
    question = await db.scalar(
        select(Message)
        .where(
            Message.consultation_id == consultation_id,
            Message.role == "user",
            Message.sequence < answer.sequence,
        )
        .order_by(Message.sequence.desc())
        .limit(1)
    )
    if question is None:
        return ExtractionOutcome("skipped", reason="no-user-message")
    return await extract_and_store(
        db, user_id, decrypt_sensitive(question.content_ciphertext), question.id
    )


EXTRACTION_SESSION_FACTORY = SessionLocal
"""Session factory used by the server-side trigger.

The answer route cannot hand over its own request session: FastAPI closes yield
dependencies when the response finishes, so extraction runs on a session of its own.
Tests point this at the transactional test session so background extraction stays inside
the same rollback scope as the request.
"""

EXTRACTION_SCHEDULING_ENABLED = True
"""Server-side trigger switch. Production keeps it on.

The test suite turns it off (see ``tests/conftest.py``): a detached task opens its own
session and may use real model credentials, which must never happen inside the test
process. Tests that do cover the trigger turn it back on and point
``EXTRACTION_SESSION_FACTORY`` at their transactional session.
"""

_extraction_semaphore: asyncio.Semaphore | None = None
_inflight_extractions: set[UUID] = set()
_scheduled_extractions: set[asyncio.Task[None]] = set()


def _extraction_semaphore_guard() -> asyncio.Semaphore:
    global _extraction_semaphore
    if _extraction_semaphore is None:
        _extraction_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    return _extraction_semaphore


async def _run_scheduled_extraction(
    user_id: UUID, user_text: str, message_id: UUID
) -> None:
    try:
        async with _extraction_semaphore_guard():
            async with EXTRACTION_SESSION_FACTORY() as session:
                await extract_and_store(session, user_id, user_text, message_id)
    except Exception as exc:  # noqa: BLE001 - detached task must never surface anywhere
        logger.warning(
            "health_record_extraction_failed code=scheduled-task error_type=%s message_id=%s",
            type(exc).__name__,
            message_id,
        )
    finally:
        _inflight_extractions.discard(message_id)


def schedule_conversation_extraction(
    *, user_id: UUID, user_text: str, message_id: UUID | None
) -> asyncio.Task[None] | None:
    """Schedule extraction for one finished turn. Best effort; never raises.

    这是「自动更新」的真实触发点：由服务端在回答落库后立刻派发，因此浏览器关闭、
    路由切换或前端请求失败都不会造成漏采。前端仍可调用 `POST /health-records/extract`
    作为幂等兜底（同一条消息由 `last_extracted_message_id` 去重）。没有任务队列，所以
    这是**尽力而为**：进程在任务完成前退出，该轮就丢一次（不影响聊天与既有记录）。
    """

    if message_id is None:
        return None
    if not EXTRACTION_SCHEDULING_ENABLED:
        return None
    decision = evaluate_health_extraction_eligibility(user_text)
    if not decision.eligible:
        logger.info(
            "health_record_extraction_skipped code=ineligible reason=%s message_id=%s",
            decision.reason,
            message_id,
        )
        return None
    if message_id in _inflight_extractions:
        return None
    try:
        task = asyncio.create_task(_run_scheduled_extraction(user_id, user_text, message_id))
    except RuntimeError:
        # No running loop (e.g. calling from a sync context in a test): skip quietly.
        return None
    _inflight_extractions.add(message_id)
    _scheduled_extractions.add(task)
    task.add_done_callback(_scheduled_extractions.discard)
    return task


async def drain_scheduled_extractions() -> None:
    """Test seam: await every extraction scheduled by the server-side trigger."""

    while _scheduled_extractions:
        await asyncio.gather(*list(_scheduled_extractions), return_exceptions=True)
