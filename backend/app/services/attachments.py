from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models import Attachment, AttachmentChunk, Consultation, MessageAttachment
from app.schemas.attachments import AttachmentList, AttachmentOut, MessageAttachmentOut
from app.services.document_extract import ExtractedDocument
from app.services.image_analysis import ImageAnalysis
from app.services.image_validation import NormalizedImage
from app.services.medical_image_storage import StoredImage


@dataclass(frozen=True)
class DeletedAttachment:
    kind: str
    storage_key: str | None


def _preview(value: str) -> str:
    clean = " ".join(value.split())
    return clean[:200] + ("…" if len(clean) > 200 else "")


def _image_available(row: Attachment, now: datetime | None = None) -> bool | None:
    if row.kind != "image":
        return None
    current = now or datetime.now(UTC)
    return bool(
        row.image_storage_key
        and row.image_key_ciphertext
        and row.image_deleted_at is None
        and row.image_expires_at
        and row.image_expires_at > current
    )


def _attachment_out(row: Attachment, preview: str) -> AttachmentOut:
    return AttachmentOut(
        id=row.id,
        display_name=decrypt_sensitive(row.display_name_ciphertext),
        kind=row.kind,
        byte_size=row.byte_size,
        page_count=row.page_count,
        char_count=row.char_count,
        preview=preview,
        status="ready",
        created_at=row.created_at,
        image_category=row.image_category,
        mime_type=row.mime_type,
        image_width=row.image_width,
        image_height=row.image_height,
        image_available=_image_available(row),
        image_expires_at=row.image_expires_at,
    )


def _message_out(row: Attachment) -> MessageAttachmentOut:
    return MessageAttachmentOut(
        id=row.id,
        display_name=decrypt_sensitive(row.display_name_ciphertext),
        kind=row.kind,
        status="ready",
        image_category=row.image_category,
        mime_type=row.mime_type,
        image_available=_image_available(row),
        image_expires_at=row.image_expires_at,
    )


async def ensure_owned_consultation(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
) -> None:
    exists = await db.scalar(
        select(Consultation.id).where(
            Consultation.id == consultation_id,
            Consultation.user_id == user_id,
        )
    )
    if exists is None:
        raise AppError(404, "CONSULTATION_NOT_FOUND", "咨询不存在或无权访问")


async def create_attachment(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
    document: ExtractedDocument,
) -> AttachmentOut:
    await ensure_owned_consultation(db, user_id, consultation_id)
    row = Attachment(
        user_id=user_id,
        consultation_id=consultation_id,
        display_name_ciphertext=encrypt_sensitive(document.display_name),
        kind=document.kind,
        byte_size=document.byte_size,
        page_count=document.page_count,
        char_count=document.char_count,
        status="ready",
    )
    db.add(row)
    await db.flush()
    db.add_all(
        [
            AttachmentChunk(
                attachment_id=row.id,
                position=chunk.position,
                locator=chunk.locator,
                content_ciphertext=encrypt_sensitive(chunk.text),
                char_count=len(chunk.text),
            )
            for chunk in document.chunks
        ]
    )
    await db.flush()
    return _attachment_out(row, document.preview)


async def create_image_attachment(
    db: AsyncSession,
    *,
    user_id: UUID,
    consultation_id: UUID,
    category: str,
    image: NormalizedImage,
    analysis: ImageAnalysis,
    stored: StoredImage,
) -> AttachmentOut:
    await ensure_owned_consultation(db, user_id, consultation_id)
    settings = get_settings()
    row = Attachment(
        user_id=user_id,
        consultation_id=consultation_id,
        display_name_ciphertext=encrypt_sensitive(image.display_name),
        kind="image",
        byte_size=image.byte_size,
        page_count=None,
        char_count=len(analysis.text),
        status="ready",
        image_category=category,
        mime_type=image.mime_type,
        image_width=image.width,
        image_height=image.height,
        image_storage_key=stored.storage_key,
        image_key_ciphertext=stored.key_ciphertext,
        image_expires_at=datetime.now(UTC) + timedelta(days=settings.image_retention_days),
        analysis_model=analysis.model,
        analysis_version=analysis.version,
    )
    db.add(row)
    await db.flush()
    chunk_size = min(settings.attachment_chunk_chars, 4000)
    chunks = [
        analysis.text[index : index + chunk_size]
        for index in range(0, len(analysis.text), chunk_size)
    ]
    db.add_all(
        [
            AttachmentChunk(
                attachment_id=row.id,
                position=position,
                locator=f"图片识别结果 {position + 1}",
                content_ciphertext=encrypt_sensitive(text),
                char_count=len(text),
            )
            for position, text in enumerate(chunks)
        ]
    )
    await db.flush()
    return _attachment_out(row, analysis.preview)


async def list_attachments(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
) -> AttachmentList:
    await ensure_owned_consultation(db, user_id, consultation_id)
    rows = (
        await db.scalars(
            select(Attachment)
            .where(
                Attachment.user_id == user_id,
                Attachment.consultation_id == consultation_id,
                ~exists().where(MessageAttachment.attachment_id == Attachment.id),
            )
            .order_by(Attachment.created_at.asc(), Attachment.id.asc())
        )
    ).all()
    if not rows:
        return AttachmentList(items=[])
    first_chunks = (
        await db.execute(
            select(AttachmentChunk.attachment_id, AttachmentChunk.content_ciphertext).where(
                AttachmentChunk.attachment_id.in_([row.id for row in rows]),
                AttachmentChunk.position == 0,
            )
        )
    ).all()
    previews = {
        attachment_id: _preview(decrypt_sensitive(ciphertext))
        for attachment_id, ciphertext in first_chunks
    }
    return AttachmentList(
        items=[_attachment_out(row, previews.get(row.id, "")) for row in rows]
    )


async def delete_attachment(
    db: AsyncSession,
    user_id: UUID,
    attachment_id: UUID,
) -> DeletedAttachment:
    row = await db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.user_id == user_id,
        )
    )
    if row is None:
        raise AppError(404, "ATTACHMENT_NOT_FOUND", "附件不存在或无权访问")
    result = DeletedAttachment(kind=row.kind, storage_key=row.image_storage_key)
    await db.delete(row)
    await db.flush()
    return result


async def get_image_attachment(
    db: AsyncSession,
    user_id: UUID,
    attachment_id: UUID,
) -> Attachment:
    row = await db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.user_id == user_id,
            Attachment.kind == "image",
        )
    )
    if row is None:
        raise AppError(404, "ATTACHMENT_NOT_FOUND", "图片不存在或无权访问")
    if not _image_available(row):
        raise AppError(410, "IMAGE_EXPIRED", "图片已过期或已被删除")
    return row


async def bind_message_attachments(
    db: AsyncSession,
    user_id: UUID,
    consultation_id: UUID,
    message_id: UUID,
    attachment_ids: list[UUID],
) -> list[MessageAttachmentOut]:
    if not attachment_ids:
        return []
    if len(attachment_ids) > 5 or len(set(attachment_ids)) != len(attachment_ids):
        raise AppError(422, "ATTACHMENT_SELECTION_INVALID", "每条消息最多选择 5 个不同附件")
    rows = (
        await db.scalars(
            select(Attachment)
            .where(
                Attachment.id.in_(attachment_ids),
                Attachment.user_id == user_id,
                Attachment.consultation_id == consultation_id,
            )
            .with_for_update()
        )
    ).all()
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(attachment_ids):
        raise AppError(404, "ATTACHMENT_NOT_FOUND", "附件不存在或不属于当前会话")
    if sum(row.kind == "image" for row in rows) > 3:
        raise AppError(422, "ATTACHMENT_SELECTION_INVALID", "每条消息最多选择 3 张图片")
    db.add_all(
        [
            MessageAttachment(
                message_id=message_id,
                attachment_id=attachment_id,
                position=position,
            )
            for position, attachment_id in enumerate(attachment_ids)
        ]
    )
    await db.flush()
    return [_message_out(by_id[attachment_id]) for attachment_id in attachment_ids]


async def copy_message_attachments(
    db: AsyncSession,
    source_message_id: UUID,
    target_message_id: UUID,
) -> None:
    links = (
        await db.scalars(
            select(MessageAttachment)
            .where(MessageAttachment.message_id == source_message_id)
            .order_by(MessageAttachment.position.asc())
        )
    ).all()
    db.add_all(
        [
            MessageAttachment(
                message_id=target_message_id,
                attachment_id=link.attachment_id,
                position=link.position,
            )
            for link in links
        ]
    )
    if links:
        await db.flush()


async def message_attachment_refs(
    db: AsyncSession,
    message_ids: list[UUID],
) -> dict[UUID, list[MessageAttachmentOut]]:
    if not message_ids:
        return {}
    rows = (
        await db.execute(
            select(MessageAttachment, Attachment)
            .outerjoin(Attachment, MessageAttachment.attachment_id == Attachment.id)
            .where(MessageAttachment.message_id.in_(message_ids))
            .order_by(MessageAttachment.message_id, MessageAttachment.position)
        )
    ).all()
    result: defaultdict[UUID, list[MessageAttachmentOut]] = defaultdict(list)
    for link, attachment in rows:
        if attachment is None:
            item = MessageAttachmentOut(
                id=None,
                display_name="附件已删除",
                kind=None,
                status="deleted",
            )
        else:
            item = _message_out(attachment)
        result[link.message_id].append(item)
    return dict(result)


async def attachment_ids_for_message(db: AsyncSession, message_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(
            select(MessageAttachment.attachment_id)
            .where(
                MessageAttachment.message_id == message_id,
                MessageAttachment.attachment_id.is_not(None),
            )
            .order_by(MessageAttachment.position)
        )
    )


async def image_storage_keys_for_consultation(
    db: AsyncSession, user_id: UUID, consultation_id: UUID
) -> list[str]:
    return list(
        await db.scalars(
            select(Attachment.image_storage_key).where(
                Attachment.user_id == user_id,
                Attachment.consultation_id == consultation_id,
                Attachment.kind == "image",
                Attachment.image_storage_key.is_not(None),
            )
        )
    )


async def image_storage_keys_for_user(db: AsyncSession, user_id: UUID) -> list[str]:
    return list(
        await db.scalars(
            select(Attachment.image_storage_key).where(
                Attachment.user_id == user_id,
                Attachment.kind == "image",
                Attachment.image_storage_key.is_not(None),
            )
        )
    )


async def delete_all_for_user(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(delete(Attachment).where(Attachment.user_id == user_id))