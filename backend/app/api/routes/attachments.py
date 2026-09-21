import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.attachments import AttachmentList, AttachmentOut
from app.services import attachments as attachment_service
from app.services.audit_logs import (
    AUDIT_OUTCOME_REJECTED,
    AUDIT_OUTCOME_SUCCESS,
    add_audit_log,
)
from app.services.document_extract import extract_document
from app.services.upload_limits import enforce_upload_rate_limit

router = APIRouter(tags=["病历附件"])
logger = logging.getLogger(__name__)
NOTICE_VERSION = "document-upload-v1"


async def _record_rejection(db: DbSession, user: CurrentUser, reason_code: str) -> None:
    try:
        await add_audit_log(
            db,
            actor_user_id=user.id,
            action="upload",
            resource_type="medical_document",
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code=reason_code,
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Failed to persist rejected document upload audit event")


@router.post(
    "/consultations/{consultation_id}/attachments",
    response_model=AttachmentOut,
    status_code=201,
    summary="在指定咨询中上传并解析一份病历文档",
)
async def upload_attachment(
    consultation_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    file: Annotated[UploadFile, File()],
    notice_accepted: Annotated[bool, Form(alias="noticeAccepted")] = False,
    notice_version: Annotated[str, Form(alias="noticeVersion")] = "",
) -> AttachmentOut:
    settings = get_settings()
    try:
        enforce_upload_rate_limit(current_user.id, "medical_document")
        if not notice_accepted or notice_version != NOTICE_VERSION:
            raise AppError(
                422,
                "DOCUMENT_NOTICE_REQUIRED",
                "上传前请确认病历文档处理与外发说明",
            )
        # Reject nonexistent or cross-user consultations before spending parser
        # CPU or exposing document contents to the isolated worker.
        await attachment_service.ensure_owned_consultation(
            db, current_user.id, consultation_id
        )
        document = await extract_document(
            file,
            max_bytes=settings.attachment_max_bytes,
            max_pages=settings.attachment_max_pages,
            max_chars=settings.attachment_max_chars,
            max_chunk_chars=settings.attachment_chunk_chars,
            timeout_seconds=settings.attachment_parse_timeout_seconds,
        )
        result = await attachment_service.create_attachment(
            db,
            current_user.id,
            consultation_id,
            document,
        )
    except AppError as exc:
        if exc.code != "UPLOAD_RATE_LIMITED":
            await _record_rejection(db, current_user, exc.code)
        raise

    await add_audit_log(
        db,
        actor_user_id=current_user.id,
        action="consent",
        resource_type="medical_document",
        resource_id=result.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
        reason_code="DOCUMENT_UPLOAD_NOTICE_V1",
    )
    await add_audit_log(
        db,
        actor_user_id=current_user.id,
        action="upload",
        resource_type="medical_document",
        resource_id=result.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/consultations/{consultation_id}/attachments",
    response_model=AttachmentList,
    summary="列出指定咨询中仍保留的附件",
)
async def get_attachments(
    consultation_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> AttachmentList:
    result = await attachment_service.list_attachments(
        db,
        current_user.id,
        consultation_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete(
    "/attachments/{attachment_id}",
    status_code=204,
    summary="删除当前用户的一份附件及其全部加密分块",
)
async def remove_attachment(
    attachment_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    await attachment_service.delete_attachment(db, current_user.id, attachment_id)
    await add_audit_log(
        db,
        actor_user_id=current_user.id,
        action="delete",
        resource_type="medical_document",
        resource_id=attachment_id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    return Response(status_code=204)
