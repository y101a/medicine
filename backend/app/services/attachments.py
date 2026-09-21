from collections import defaultdict
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models import Attachment, AttachmentChunk, Consultation, MessageAttachment
from app.schemas.attachments import AttachmentList, AttachmentOut, MessageAttachmentOut
from app.services.document_extract import ExtractedDocument


def _preview(value: str) -> str:
    clean = " ".join(value.split())
    return clean[:200] + ("…" if len(clean) > 200 else "")


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
) -> bool:
    row = await db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.user_id == user_id,
        )
    )
    if row is None:
        raise AppError(404, "ATTACHMENT_NOT_FOUND", "附件不存在或无权访问")
    await db.delete(row)
    await db.flush()
    return True


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
    return [
        MessageAttachmentOut(
            id=attachment_id,
            display_name=decrypt_sensitive(by_id[attachment_id].display_name_ciphertext),
            kind=by_id[attachment_id].kind,
            status="ready",
        )
        for attachment_id in attachment_ids
    ]


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
            item = MessageAttachmentOut(
                id=attachment.id,
                display_name=decrypt_sensitive(attachment.display_name_ciphertext),
                kind=attachment.kind,
                status="ready",
            )
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


async def delete_all_for_user(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(delete(Attachment).where(Attachment.user_id == user_id))
