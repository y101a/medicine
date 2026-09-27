"""Persistent medical educational DOCX/PPTX generation workflow."""

from __future__ import annotations

import json
import secrets
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.privacy import redact_direct_identifiers
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models import (
    Consultation,
    GeneratedDocument,
    GeneratedDocumentFile,
    Message,
    MessageAttachment,
    User,
)
from app.rag.retrieval import RetrievalError, search_knowledge
from app.schemas.document_generations import (
    CreateDocumentGeneration,
    DocumentGenerationList,
    DocumentGenerationOut,
    GeneratedDocumentFileOut,
)
from app.services.audit_logs import AUDIT_OUTCOME_REJECTED, AUDIT_OUTCOME_SUCCESS, add_audit_log
from app.services.document_generation_content import (
    generate_content_plan,
    source_snapshots,
)
from app.services.document_generation_intent import (
    DocumentGenerationRequest,
    medical_document_generation_request,
    request_contains_forbidden_document,
)
from app.services.document_renderers import render_docx, render_pptx
from app.services.generated_document_deletion import (
    enqueue_document_deletions,
    process_document_deletion_jobs_best_effort,
)
from app.services.generated_document_storage import (
    load_generated_document,
    remove_generated_document,
    store_generated_document,
)
from app.services.generated_document_validation import validate_generated_document

NOTICE_VERSION = "document-generation-v1"
ACTIVE_STATUSES = ("queued", "generating", "rendering")
MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _files_out(
    files: list[GeneratedDocumentFile],
    *,
    available: bool,
) -> list[GeneratedDocumentFileOut]:
    return [
        GeneratedDocumentFileOut(
            id=item.id,
            format=item.format,
            mime_type=item.mime_type,
            byte_size=item.byte_size,
            page_count=item.page_count,
            available=available,
        )
        for item in sorted(files, key=lambda value: value.format)
    ]


def _out(
    row: GeneratedDocument,
    files: list[GeneratedDocumentFile],
    *,
    now: datetime | None = None,
) -> DocumentGenerationOut:
    current = now or datetime.now(UTC)
    status = row.status
    if status == "completed" and row.expires_at and row.expires_at <= current:
        status = "expired"
    available = status == "completed" and bool(row.expires_at and row.expires_at > current)
    title = decrypt_sensitive(row.title_ciphertext) if row.title_ciphertext else None
    return DocumentGenerationOut(
        id=row.id,
        source_message_id=row.source_message_id,
        status=status,
        formats=row.requested_formats,
        title=title,
        model=row.model,
        files=_files_out(files, available=available),
        source_count=row.source_count,
        error_code=row.error_code,
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _files_by_generation(
    db: AsyncSession,
    generation_ids: list[UUID],
) -> dict[UUID, list[GeneratedDocumentFile]]:
    grouped: dict[UUID, list[GeneratedDocumentFile]] = defaultdict(list)
    if not generation_ids:
        return grouped
    rows = (
        await db.scalars(
            select(GeneratedDocumentFile).where(
                GeneratedDocumentFile.generation_id.in_(generation_ids)
            )
        )
    ).all()
    for row in rows:
        grouped[row.generation_id].append(row)
    return grouped


async def _owned_source(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
    source_message_id: UUID,
) -> tuple[Message, DocumentGenerationRequest, str]:
    row = await db.scalar(
        select(Message)
        .join(Consultation, Consultation.id == Message.consultation_id)
        .where(
            Message.id == source_message_id,
            Message.consultation_id == consultation_id,
            Consultation.user_id == user_id,
        )
    )
    if row is None or row.role != "user" or row.triage_ciphertext is not None:
        raise AppError(
            422,
            "DOCUMENT_GENERATION_SOURCE_INVALID",
            "只能根据本轮明确的医学科普文档请求生成文件",
        )
    attachment = await db.scalar(
        select(MessageAttachment.message_id).where(MessageAttachment.message_id == row.id).limit(1)
    )
    if attachment is not None:
        raise AppError(
            422,
            "DOCUMENT_GENERATION_SOURCE_INVALID",
            "第一版不能读取附件生成 PPT 或 Word",
        )
    content = decrypt_sensitive(row.content_ciphertext)
    request = medical_document_generation_request(content)
    if request is None:
        raise AppError(
            422,
            "DOCUMENT_GENERATION_SOURCE_INVALID",
            "请在同一条消息中明确医学主题以及 PPT 或 Word 格式",
        )
    if request_contains_forbidden_document(content):
        raise AppError(
            422,
            "DOCUMENT_GENERATION_CONTENT_REJECTED",
            "不能生成诊断证明、处方或其他可冒充真实医疗材料的文档",
        )
    topic, _ = redact_direct_identifiers(request.topic)
    if len(topic.replace("[个人信息已移除]", "").strip()) < 2:
        raise AppError(422, "DOCUMENT_GENERATION_REQUEST_INVALID", "移除个人信息后缺少有效主题")
    return row, request, topic


async def _enforce_limits(db: AsyncSession, user_id: UUID, now: datetime) -> None:
    settings = get_settings()
    ten_minutes = await db.scalar(
        select(func.count(GeneratedDocument.id)).where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.created_at >= now - timedelta(minutes=10),
        )
    )
    day_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    today = await db.scalar(
        select(func.count(GeneratedDocument.id)).where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.created_at >= day_start,
        )
    )
    if (ten_minutes or 0) >= settings.document_generation_limit_10m or (
        today or 0
    ) >= settings.document_generation_limit_daily:
        raise AppError(
            429,
            "DOCUMENT_GENERATION_RATE_LIMITED",
            "文档生成次数已达限制，请稍后再试",
        )


async def create(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
    payload: CreateDocumentGeneration,
) -> DocumentGenerationOut:
    existing = await db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.client_request_id == payload.client_request_id,
        )
    )
    if existing is not None:
        files = await _files_by_generation(db, [existing.id])
        return _out(existing, files[existing.id])
    existing_source = await db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.source_message_id == payload.source_message_id,
        )
    )
    if existing_source is not None:
        files = await _files_by_generation(db, [existing_source.id])
        return _out(existing_source, files[existing_source.id])
    if not payload.notice_accepted or payload.notice_version != NOTICE_VERSION:
        raise AppError(
            422,
            "DOCUMENT_GENERATION_NOTICE_REQUIRED",
            "生成前请确认 AI 文档处理、费用和 30 天保留说明",
        )
    await db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    existing = await db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.client_request_id == payload.client_request_id,
        )
    )
    if existing is not None:
        files = await _files_by_generation(db, [existing.id])
        return _out(existing, files[existing.id])
    active = await db.scalar(
        select(GeneratedDocument.id).where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.status.in_(ACTIVE_STATUSES),
        )
    )
    if active is not None:
        raise AppError(409, "DOCUMENT_GENERATION_ACTIVE", "已有一份文档正在生成")
    _, request, _ = await _owned_source(
        db,
        user_id,
        consultation_id,
        payload.source_message_id,
    )
    now = datetime.now(UTC)
    await _enforce_limits(db, user_id, now)
    settings = get_settings()
    row = GeneratedDocument(
        user_id=user_id,
        consultation_id=consultation_id,
        source_message_id=payload.source_message_id,
        client_request_id=payload.client_request_id,
        requested_formats=list(request.formats),
        status="queued",
        model=settings.document_generation_model,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    await add_audit_log(
        db,
        actor_user_id=user_id,
        action="consent",
        resource_type="generated_document",
        resource_id=row.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
        reason_code="DOCUMENT_GENERATION_NOTICE_V1",
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, [])


async def _expire(
    db: AsyncSession,
    row: GeneratedDocument,
    files: list[GeneratedDocumentFile],
) -> None:
    keys = [item.storage_key for item in files]
    await enqueue_document_deletions(db, keys, "GENERATED_DOCUMENT_EXPIRED")
    await db.execute(
        delete(GeneratedDocumentFile).where(GeneratedDocumentFile.generation_id == row.id)
    )
    row.status = "expired"
    row.title_ciphertext = None
    row.content_plan_ciphertext = None
    row.source_snapshot_ciphertext = None
    row.expires_at = None
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await process_document_deletion_jobs_best_effort(db, storage_keys=keys)


async def get(db: AsyncSession, user_id: UUID, generation_id: UUID) -> DocumentGenerationOut:
    row = await db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.id == generation_id,
            GeneratedDocument.user_id == user_id,
        )
    )
    if row is None:
        raise AppError(404, "DOCUMENT_GENERATION_NOT_FOUND", "文档生成任务不存在")
    grouped = await _files_by_generation(db, [row.id])
    files = grouped[row.id]
    if row.status == "completed" and row.expires_at and row.expires_at <= datetime.now(UTC):
        await _expire(db, row, files)
        files = []
    return _out(row, files)


async def list_for_consultation(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
) -> DocumentGenerationList:
    owned = await db.scalar(
        select(Consultation.id).where(
            Consultation.id == consultation_id,
            Consultation.user_id == user_id,
        )
    )
    if owned is None:
        raise AppError(404, "CONSULTATION_NOT_FOUND", "咨询不存在或无权访问")
    rows = (
        await db.scalars(
            select(GeneratedDocument)
            .where(
                GeneratedDocument.user_id == user_id,
                GeneratedDocument.consultation_id == consultation_id,
            )
            .order_by(GeneratedDocument.created_at.asc(), GeneratedDocument.id.asc())
        )
    ).all()
    grouped = await _files_by_generation(db, [row.id for row in rows])
    return DocumentGenerationList(items=[_out(row, grouped[row.id]) for row in rows])


async def content(
    db: AsyncSession,
    user_id: UUID,
    generation_id: UUID,
    file_id: UUID,
) -> tuple[bytes, GeneratedDocumentFile]:
    result = (
        await db.execute(
            select(GeneratedDocument, GeneratedDocumentFile)
            .join(
                GeneratedDocumentFile,
                GeneratedDocumentFile.generation_id == GeneratedDocument.id,
            )
            .where(
                GeneratedDocument.id == generation_id,
                GeneratedDocument.user_id == user_id,
                GeneratedDocumentFile.id == file_id,
            )
        )
    ).one_or_none()
    if result is None:
        raise AppError(404, "DOCUMENT_GENERATION_NOT_FOUND", "生成文件不存在")
    row, file = result
    if row.status == "expired" or (row.expires_at and row.expires_at <= datetime.now(UTC)):
        grouped = await _files_by_generation(db, [row.id])
        if row.status == "completed":
            await _expire(db, row, grouped[row.id])
        raise AppError(410, "GENERATED_DOCUMENT_EXPIRED", "生成文档已过期或已删除")
    if row.status != "completed":
        raise AppError(409, "DOCUMENT_GENERATION_NOT_READY", "文档尚未生成完成")
    payload = await load_generated_document(
        file.storage_key,
        file.file_key_ciphertext,
        row.id,
        file.format,
    )
    return payload, file


async def remove(db: AsyncSession, user_id: UUID, generation_id: UUID) -> list[str]:
    row = await db.scalar(
        select(GeneratedDocument)
        .where(
            GeneratedDocument.id == generation_id,
            GeneratedDocument.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "DOCUMENT_GENERATION_NOT_FOUND", "文档生成任务不存在")
    grouped = await _files_by_generation(db, [row.id])
    keys = [item.storage_key for item in grouped[row.id]]
    if row.status in ACTIVE_STATUSES:
        row.status = "cancelled"
        row.cancelled_at = datetime.now(UTC)
        row.lease_owner = None
        row.lease_expires_at = None
        row.updated_at = row.cancelled_at
    else:
        await enqueue_document_deletions(db, keys, "GENERATED_DOCUMENT_DELETED")
        await db.delete(row)
    await add_audit_log(
        db,
        actor_user_id=user_id,
        action="delete",
        resource_type="generated_document",
        resource_id=generation_id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    await process_document_deletion_jobs_best_effort(db, storage_keys=keys)
    return keys


async def storage_keys_for_consultation(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
) -> list[str]:
    return list(
        await db.scalars(
            select(GeneratedDocumentFile.storage_key)
            .join(GeneratedDocument, GeneratedDocument.id == GeneratedDocumentFile.generation_id)
            .where(
                GeneratedDocument.user_id == user_id,
                GeneratedDocument.consultation_id == consultation_id,
            )
        )
    )


async def storage_keys_for_user(db: AsyncSession, user_id: UUID) -> list[str]:
    return list(
        await db.scalars(
            select(GeneratedDocumentFile.storage_key)
            .join(GeneratedDocument, GeneratedDocument.id == GeneratedDocumentFile.generation_id)
            .where(GeneratedDocument.user_id == user_id)
        )
    )


async def _mark_failed(
    db: AsyncSession,
    generation_id: UUID,
    error: AppError,
    stored_keys: list[str],
) -> None:
    await db.rollback()
    row = await db.scalar(
        select(GeneratedDocument).where(GeneratedDocument.id == generation_id).with_for_update()
    )
    if row is None:
        for key in stored_keys:
            try:
                await remove_generated_document(key)
            except (OSError, ValueError):
                pass
        return
    if stored_keys:
        await enqueue_document_deletions(db, stored_keys, "DOCUMENT_GENERATION_ROLLBACK")
    if row.status != "cancelled":
        row.status = "failed"
        row.error_code = error.code
        row.updated_at = datetime.now(UTC)
    row.lease_owner = None
    row.lease_expires_at = None
    await add_audit_log(
        db,
        actor_user_id=row.user_id,
        action="generate",
        resource_type="generated_document",
        resource_id=row.id,
        outcome=AUDIT_OUTCOME_REJECTED,
        reason_code=error.code,
    )
    await db.commit()
    await process_document_deletion_jobs_best_effort(db, storage_keys=stored_keys)


async def process_one(db: AsyncSession, generation_id: UUID) -> bool:
    row = await db.scalar(
        select(GeneratedDocument).where(GeneratedDocument.id == generation_id).with_for_update()
    )
    if row is None or row.status not in ACTIVE_STATUSES:
        await db.rollback()
        return False
    _, request, topic = await _owned_source(
        db,
        row.user_id,
        row.consultation_id,
        row.source_message_id,
    )
    if list(request.formats) != row.requested_formats:
        await db.rollback()
        await _mark_failed(
            db,
            row.id,
            AppError(422, "DOCUMENT_GENERATION_SOURCE_INVALID", "原始请求格式已发生冲突"),
            [],
        )
        return False
    row.status = "generating"
    row.attempt_count += 1
    row.updated_at = datetime.now(UTC)
    await db.commit()

    stored_keys: list[str] = []
    try:
        try:
            retrieval = await search_knowledge(db, topic, top_k=8, mode="hybrid")
        except RetrievalError as exc:
            raise AppError(exc.status_code, exc.code, str(exc)) from exc
        if not retrieval.items:
            raise AppError(
                422,
                "DOCUMENT_EVIDENCE_INSUFFICIENT",
                "当前知识库缺少足够的可引用资料，暂时不能生成该科普文档",
            )
        await db.commit()
        snapshots = source_snapshots(retrieval.items)
        plan = await generate_content_plan(topic, retrieval.items)

        locked = await db.scalar(
            select(GeneratedDocument).where(GeneratedDocument.id == generation_id).with_for_update()
        )
        if locked is None or locked.status == "cancelled":
            await db.rollback()
            return False
        locked.status = "rendering"
        locked.updated_at = datetime.now(UTC)
        await db.commit()

        rendered: list[tuple[str, bytes, int | None]] = []
        if "docx" in locked.requested_formats:
            rendered.append(("docx", render_docx(plan, snapshots), None))
        if "pptx" in locked.requested_formats:
            pptx_bytes, slides = render_pptx(plan, snapshots)
            rendered.append(("pptx", pptx_bytes, slides))

        settings = get_settings()
        files: list[GeneratedDocumentFile] = []
        for format, payload, page_count in rendered:
            validate_generated_document(
                payload,
                format,
                max_bytes=settings.document_generation_max_bytes,
            )
            stored = await store_generated_document(payload, locked.id, format)
            stored_keys.append(stored.storage_key)
            files.append(
                GeneratedDocumentFile(
                    generation_id=locked.id,
                    format=format,
                    storage_key=stored.storage_key,
                    file_key_ciphertext=stored.key_ciphertext,
                    mime_type=MIME_TYPES[format],
                    byte_size=len(payload),
                    page_count=page_count,
                    content_sha256=stored.content_sha256,
                )
            )

        final = await db.scalar(
            select(GeneratedDocument).where(GeneratedDocument.id == generation_id).with_for_update()
        )
        if final is None or final.status == "cancelled":
            raise AppError(409, "DOCUMENT_GENERATION_CANCELLED", "文档生成已取消")
        now = datetime.now(UTC)
        db.add_all(files)
        final.status = "completed"
        final.title_ciphertext = encrypt_sensitive(plan.title)
        final.content_plan_ciphertext = encrypt_sensitive(
            plan.model_dump_json(by_alias=True, exclude_none=True)
        )
        final.source_snapshot_ciphertext = encrypt_sensitive(
            json.dumps(snapshots, ensure_ascii=False, separators=(",", ":"))
        )
        final.source_count = len(snapshots)
        final.error_code = None
        final.expires_at = now + timedelta(days=settings.document_generation_retention_days)
        final.completed_at = now
        final.updated_at = now
        final.lease_owner = None
        final.lease_expires_at = None
        await add_audit_log(
            db,
            actor_user_id=final.user_id,
            action="generate",
            resource_type="generated_document",
            resource_id=final.id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            reason_code=settings.document_generation_model,
        )
        await db.commit()
        return True
    except AppError as exc:
        await _mark_failed(db, generation_id, exc, stored_keys)
        return False
    except Exception:
        await _mark_failed(
            db,
            generation_id,
            AppError(500, "DOCUMENT_RENDER_FAILED", "文档生成失败"),
            stored_keys,
        )
        return False


async def process_due(db: AsyncSession, *, limit: int = 10) -> tuple[int, int]:
    now = datetime.now(UTC)
    candidates = (
        await db.scalars(
            select(GeneratedDocument.id)
            .where(
                GeneratedDocument.status.in_(ACTIVE_STATUSES),
                or_(
                    GeneratedDocument.lease_expires_at.is_(None),
                    GeneratedDocument.lease_expires_at <= now,
                ),
            )
            .order_by(GeneratedDocument.created_at.asc())
            .limit(limit)
        )
    ).all()
    completed = failed = 0
    for generation_id in candidates:
        row = await db.scalar(
            select(GeneratedDocument)
            .where(GeneratedDocument.id == generation_id)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            await db.rollback()
            continue
        if row.status not in ACTIVE_STATUSES or (
            row.lease_expires_at is not None and row.lease_expires_at > now
        ):
            await db.rollback()
            continue
        row.lease_owner = secrets.token_hex(16)
        row.lease_expires_at = now + timedelta(
            seconds=get_settings().document_generation_lease_seconds
        )
        await db.commit()
        if await process_one(db, generation_id):
            completed += 1
        else:
            failed += 1
    return completed, failed


async def cleanup_expired(db: AsyncSession, *, limit: int = 200) -> int:
    now = datetime.now(UTC)
    rows = (
        await db.scalars(
            select(GeneratedDocument)
            .where(
                GeneratedDocument.status == "completed",
                GeneratedDocument.expires_at <= now,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in rows:
        grouped = await _files_by_generation(db, [row.id])
        await _expire(db, row, grouped[row.id])
    return len(rows)
