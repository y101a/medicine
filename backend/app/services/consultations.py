import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.follow_up import follow_up_fallback, parse_follow_up
from app.ai.graph import run_consultation_safety
from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models import Consultation, Message
from app.safety.triage import deserialize_triage, serialize_triage
from app.schemas.attachments import MessageAttachmentOut
from app.schemas.consultations import (
    ConsultationOut,
    ConsultationPage,
    CreateMessage,
    MessageCitation,
    MessageOut,
    MessagePage,
    TriageResult,
)
from app.services import attachments as attachment_service
from app.services import document_generations as document_generation_service
from app.services import image_generations as image_generation_service
from app.services.document_generation_intent import medical_document_generation_request
from app.services.generated_document_deletion import (
    enqueue_document_deletions,
    process_document_deletion_jobs_best_effort,
)
from app.services.image_deletion import (
    enqueue_image_deletions,
    process_image_deletion_jobs_best_effort,
)
from app.services.image_generation_intent import medical_image_generation_prompt
from app.services.speech_intent import speech_output_request


def summary(row: Consultation) -> ConsultationOut:
    return ConsultationOut(
        id=row.id,
        title=decrypt_sensitive(row.title_ciphertext),
        message_count=row.message_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def message_out(
    row: Message,
    attachments: list[MessageAttachmentOut] | None = None,
) -> MessageOut:
    stored_content = decrypt_sensitive(row.content_ciphertext)
    follow_up = parse_follow_up(stored_content)
    triage = deserialize_triage(
        decrypt_sensitive(row.triage_ciphertext) if row.triage_ciphertext else None
    )
    citations = deserialize_citations(
        decrypt_sensitive(row.citations_ciphertext) if row.citations_ciphertext else None
    )
    document_request = (
        medical_document_generation_request(stored_content)
        if row.role == "user" and triage is None and not attachments
        else None
    )
    image_request = bool(
        row.role == "user"
        and triage is None
        and not attachments
        and document_request is None
        and medical_image_generation_prompt(stored_content)
    )
    speech_request = (
        speech_output_request(stored_content)
        if row.role == "user"
        and triage is None
        and document_request is None
        and not image_request
        else None
    )
    return MessageOut(
        id=row.id,
        role=row.role,
        content=follow_up_fallback(follow_up) if follow_up else stored_content,
        sequence=row.sequence,
        provider=row.provider,
        model_id=row.model_id,
        model_name=row.model_name,
        generation_status=row.generation_status,
        answer_format=row.answer_format,
        medical_content=row.is_medical_content,
        image_generation_intent=image_request,
        document_generation_intent=document_request is not None,
        speech_output_intent=speech_request,
        source_message_id=row.source_message_id,
        follow_up=follow_up,
        triage=triage,
        citations=citations,
        attachments=attachments or [],
        created_at=row.created_at,
    )


def serialize_citations(citations: list[dict[str, Any]] | None) -> str | None:
    if not citations:
        return None
    validated = [MessageCitation.model_validate(item) for item in citations]
    return json.dumps(
        [item.model_dump(mode="json") for item in validated],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def deserialize_citations(payload: str | None) -> list[MessageCitation]:
    if not payload:
        return []
    try:
        parsed = json.loads(payload)
        if not isinstance(parsed, list):
            return []
        return [MessageCitation.model_validate(item) for item in parsed]
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


async def owned(db: AsyncSession, user_id: UUID, cid: UUID, lock: bool = False) -> Consultation:
    query = select(Consultation).where(Consultation.id == cid, Consultation.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise AppError(404, "CONSULTATION_NOT_FOUND", "咨询不存在或无权访问")
    return row


async def create(db: AsyncSession, user_id: UUID, request_id: UUID) -> ConsultationOut:
    await db.execute(
        insert(Consultation)
        .values(
            id=uuid4(),
            user_id=user_id,
            client_request_id=request_id,
            title_ciphertext=encrypt_sensitive("新咨询"),
            message_count=0,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "client_request_id"])
    )
    row = await db.scalar(
        select(Consultation).where(
            Consultation.user_id == user_id,
            Consultation.client_request_id == request_id,
        )
    )
    result = summary(row)
    await db.commit()
    return result


async def list_consultations(db: AsyncSession, user_id: UUID, offset: int, limit: int):
    rows = (
        await db.scalars(
            select(Consultation)
            .where(Consultation.user_id == user_id)
            .order_by(Consultation.updated_at.desc(), Consultation.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()
    return ConsultationPage(
        items=[summary(row) for row in rows[:limit]], has_more=len(rows) > limit
    )


async def list_messages(db: AsyncSession, user_id: UUID, cid: UUID, before: int | None, limit: int):
    await owned(db, user_id, cid)
    query = select(Message).where(Message.consultation_id == cid)
    if before is not None:
        query = query.where(Message.sequence < before)
    rows = (await db.scalars(query.order_by(Message.sequence.desc()).limit(limit + 1))).all()
    visible = list(reversed(rows[:limit]))
    refs = await attachment_service.message_attachment_refs(db, [row.id for row in visible])
    return MessagePage(
        items=[message_out(row, refs.get(row.id, [])) for row in visible],
        has_more=len(rows) > limit,
    )


async def ai_history(db: AsyncSession, user_id: UUID, cid: UUID, limit: int = 30):
    await owned(db, user_id, cid)
    rows = (
        await db.scalars(
            select(Message)
            .where(Message.consultation_id == cid)
            .order_by(Message.sequence.desc())
            .limit(limit)
        )
    ).all()
    history = [
        {"role": row.role, "content": decrypt_sensitive(row.content_ciphertext)}
        for row in reversed(rows)
    ]
    if not history or history[-1]["role"] != "user":
        raise AppError(409, "NO_PENDING_USER_MESSAGE", "请先发送新的健康问题")
    triage = deserialize_triage(
        decrypt_sensitive(rows[0].triage_ciphertext) if rows[0].triage_ciphertext else None
    )
    return history, triage, rows[0].id


async def latest_card_source(db: AsyncSession, user_id: UUID, cid: UUID) -> UUID:
    """Only the immediately preceding answer may be selected implicitly."""
    await owned(db, user_id, cid)
    source = await db.scalar(
        select(Message)
        .where(Message.consultation_id == cid, Message.role == "assistant")
        .order_by(Message.sequence.desc())
        .limit(1)
    )
    if source is None:
        raise AppError(409, "PATHOLOGY_CARD_TOPIC_REQUIRED", "请说明要生成哪个健康主题的科普卡片")
    # The existing source validator rejects non-medical, failed and card answers.
    return source.id


async def card_generation_history(
    db: AsyncSession,
    user_id: UUID,
    cid: UUID,
    source_message_id: UUID,
    limit: int = 30,
) -> tuple[list[dict[str, str]], str]:
    await owned(db, user_id, cid)
    source = await db.scalar(
        select(Message).where(
            Message.id == source_message_id,
            Message.consultation_id == cid,
        )
    )
    if (
        source is None
        or source.role != "assistant"
        or source.answer_format != "plain"
        or source.generation_status != "completed"
        or not source.is_medical_content
    ):
        raise AppError(409, "PATHOLOGY_CARD_SOURCE_INVALID", "该回答不能生成病理科普卡片")
    existing_card = await db.scalar(
        select(Message).where(Message.source_message_id == source_message_id)
    )
    if existing_card is not None:
        raise AppError(409, "PATHOLOGY_CARD_EXISTS", "该回答已生成病理科普卡片")
    user_message = await db.scalar(
        select(Message)
        .where(
            Message.consultation_id == cid,
            Message.role == "user",
            Message.sequence < source.sequence,
        )
        .order_by(Message.sequence.desc())
        .limit(1)
    )
    if user_message is None:
        raise AppError(409, "PATHOLOGY_CARD_SOURCE_INVALID", "未找到原始健康问题")
    rows = (
        await db.scalars(
            select(Message)
            .where(
                Message.consultation_id == cid,
                Message.sequence <= user_message.sequence,
            )
            .order_by(Message.sequence.desc())
            .limit(limit)
        )
    ).all()
    history = [
        {"role": row.role, "content": decrypt_sensitive(row.content_ciphertext)}
        for row in reversed(rows)
    ]
    return history, decrypt_sensitive(user_message.content_ciphertext)


async def pending_triage(db: AsyncSession, user_id: UUID, cid: UUID):
    await owned(db, user_id, cid)
    row = await db.scalar(
        select(Message)
        .where(Message.consultation_id == cid)
        .order_by(Message.sequence.desc())
        .limit(1)
    )
    if row is None or row.role != "user" or not row.triage_ciphertext:
        return None
    return deserialize_triage(decrypt_sensitive(row.triage_ciphertext))


async def append_message(db: AsyncSession, user_id: UUID, cid: UUID, payload: CreateMessage):
    # Serialize writes with deletion and other sends to keep sequence numbers stable.
    conversation = await owned(db, user_id, cid, lock=True)
    existing = await db.scalar(
        select(Message).where(
            Message.consultation_id == cid,
            Message.client_request_id == payload.client_request_id,
        )
    )
    if existing is not None:
        existing_attachment_ids = await attachment_service.attachment_ids_for_message(
            db, existing.id
        )
        if (
            decrypt_sensitive(existing.content_ciphertext) != payload.content
            or existing_attachment_ids != payload.attachment_ids
        ):
            raise AppError(409, "REQUEST_CONFLICT", "该请求编号已用于其他消息")
        refs = await attachment_service.message_attachment_refs(db, [existing.id])
        result = message_out(existing, refs.get(existing.id, []))
        await db.commit()
        return result
    conversation.message_count += 1
    conversation.updated_at = datetime.now(UTC)
    if conversation.message_count == 1:
        conversation.title_ciphertext = encrypt_sensitive(payload.content[:40])
    graph_result = await run_consultation_safety(payload.content)
    triage_payload = graph_result["triage_result"]
    triage = TriageResult.model_validate(triage_payload) if triage_payload else None
    row = Message(
        consultation_id=cid,
        client_request_id=payload.client_request_id,
        sequence=conversation.message_count,
        content_ciphertext=encrypt_sensitive(payload.content),
        role="user",
        triage_ciphertext=encrypt_sensitive(serialize_triage(triage)) if triage else None,
    )
    db.add(row)
    await db.flush()
    refs = await attachment_service.bind_message_attachments(
        db, user_id, cid, row.id, payload.attachment_ids
    )
    result = message_out(row, refs)
    await db.commit()
    return result


async def append_assistant_message(
    db: AsyncSession,
    user_id: UUID,
    cid: UUID,
    request_id: UUID,
    content: str,
    provider: str,
    model_id: str,
    model_name: str,
    generation_status: str = "completed",
    citations: list[dict[str, Any]] | None = None,
    answer_format: str = "plain",
    medical_content: bool = False,
    source_message_id: UUID | None = None,
) -> MessageOut:
    conversation = await owned(db, user_id, cid, lock=True)
    existing = await db.scalar(
        select(Message).where(
            Message.consultation_id == cid,
            Message.client_request_id == request_id,
        )
    )
    if existing is not None:
        if existing.role != "assistant":
            raise AppError(409, "REQUEST_CONFLICT", "该请求编号已用于其他消息")
        if (
            existing.provider != provider
            or existing.model_id != model_id
            or existing.model_name != model_name
            or existing.answer_format != answer_format
            or existing.source_message_id != source_message_id
        ):
            raise AppError(409, "REQUEST_CONFLICT", "该请求编号已用于其他模型")
        refs = await attachment_service.message_attachment_refs(db, [existing.id])
        result = message_out(existing, refs.get(existing.id, []))
        await db.commit()
        return result
    if source_message_id is not None:
        existing_card = await db.scalar(
            select(Message).where(Message.source_message_id == source_message_id)
        )
        if existing_card is not None:
            raise AppError(409, "PATHOLOGY_CARD_EXISTS", "该回答已生成病理科普卡片")
    clean_content = content.strip()
    if not clean_content:
        raise AppError(502, "AI_EMPTY_RESPONSE", "AI 服务未返回有效内容")
    conversation.message_count += 1
    conversation.updated_at = datetime.now(UTC)
    row = Message(
        consultation_id=cid,
        client_request_id=request_id,
        sequence=conversation.message_count,
        content_ciphertext=encrypt_sensitive(clean_content),
        role="assistant",
        provider=provider,
        model_id=model_id,
        model_name=model_name,
        generation_status=generation_status,
        answer_format=answer_format,
        is_medical_content=medical_content,
        source_message_id=source_message_id,
        citations_ciphertext=(
            encrypt_sensitive(serialized_citations)
            if (serialized_citations := serialize_citations(citations))
            else None
        ),
    )
    db.add(row)
    await db.flush()
    if source_message_id is None:
        user_message_id = await db.scalar(
            select(Message.id)
            .where(
                Message.consultation_id == cid,
                Message.role == "user",
                Message.sequence < row.sequence,
            )
            .order_by(Message.sequence.desc())
            .limit(1)
        )
        if user_message_id is not None:
            await attachment_service.copy_message_attachments(db, user_message_id, row.id)
    refs = await attachment_service.message_attachment_refs(db, [row.id])
    result = message_out(row, refs.get(row.id, []))
    await db.commit()
    return result


async def remove(db: AsyncSession, user_id: UUID, cid: UUID):
    await owned(db, user_id, cid, lock=True)
    image_keys = await attachment_service.image_storage_keys_for_consultation(db, user_id, cid)
    image_keys.extend(
        await image_generation_service.storage_keys_for_consultation(db, user_id, cid)
    )
    document_keys = await document_generation_service.storage_keys_for_consultation(
        db, user_id, cid
    )
    await enqueue_image_deletions(
        db,
        image_keys,
        "CONSULTATION_DELETED",
    )
    await enqueue_document_deletions(
        db,
        document_keys,
        "CONSULTATION_DELETED",
    )
    await db.execute(
        delete(Consultation).where(
            Consultation.id == cid,
            Consultation.user_id == user_id,
        )
    )
    await db.commit()
    await process_image_deletion_jobs_best_effort(
        db,
        storage_keys=image_keys,
    )
    await process_document_deletion_jobs_best_effort(
        db,
        storage_keys=document_keys,
    )
