"""Authenticated medical image upload, analysis and content retrieval."""

from __future__ import annotations

import logging
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.attachments import AttachmentOut
from app.services import attachments as attachment_service
from app.services.audit_logs import (
    AUDIT_OUTCOME_REJECTED,
    AUDIT_OUTCOME_SUCCESS,
    add_audit_log,
)
from app.services.image_analysis import analyze_image
from app.services.image_validation import normalize_image
from app.services.medical_image_storage import load_image, remove_image, store_image
from app.services.upload_limits import enforce_upload_rate_limit

router = APIRouter(tags=["医学图片"])
logger = logging.getLogger(__name__)
NOTICE_VERSION = "medical-image-upload-v1"
ImageCategory = Literal["report", "medical_imaging", "body_photo"]


async def _record_rejection(db: DbSession, user: CurrentUser, reason_code: str) -> None:
    try:
        await db.rollback()
        await add_audit_log(
            db,
            actor_user_id=user.id,
            action="upload",
            resource_type="medical_image",
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code=reason_code,
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Failed to persist rejected medical image audit event")


@router.post(
    "/consultations/{consultation_id}/images",
    response_model=AttachmentOut,
    status_code=201,
    summary="上传、规范化并受限识别一张医学相关图片",
)
async def upload_medical_image(
    consultation_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    file: Annotated[UploadFile, File()],
    category: Annotated[str, Form(alias="imageCategory")],
    notice_accepted: Annotated[bool, Form(alias="noticeAccepted")] = False,
    notice_version: Annotated[str, Form(alias="noticeVersion")] = "",
) -> AttachmentOut:
    settings = get_settings()
    storage_key: str | None = None
    try:
        enforce_upload_rate_limit(current_user.id, "medical_image")
        if category not in {"report", "medical_imaging", "body_photo"}:
            raise AppError(422, "IMAGE_CATEGORY_INVALID", "请选择正确的图片类别")
        category_value = cast(ImageCategory, category)
        if not notice_accepted or notice_version != NOTICE_VERSION:
            raise AppError(
                422,
                "IMAGE_NOTICE_REQUIRED",
                "上传前请确认图片处理、外发和保留期限说明",
            )
        await attachment_service.ensure_owned_consultation(
            db, current_user.id, consultation_id
        )
        image = await normalize_image(
            file,
            max_bytes=settings.image_max_bytes,
            max_pixels=settings.image_max_pixels,
            max_dimension=settings.image_max_dimension,
        )
        analysis = await analyze_image(image, category_value)
        stored = await store_image(image.content)
        storage_key = stored.storage_key
        result = await attachment_service.create_image_attachment(
            db,
            user_id=current_user.id,
            consultation_id=consultation_id,
            category=category_value,
            image=image,
            analysis=analysis,
            stored=stored,
        )
    except AppError as exc:
        if storage_key:
            await remove_image(storage_key)
        if exc.code != "UPLOAD_RATE_LIMITED":
            await _record_rejection(db, current_user, exc.code)
        raise
    except SQLAlchemyError as exc:
        if storage_key:
            await remove_image(storage_key)
        await _record_rejection(db, current_user, "IMAGE_SAVE_FAILED")
        raise AppError(500, "IMAGE_SAVE_FAILED", "图片保存失败，请稍后重试") from exc

    try:
        await add_audit_log(
            db,
            actor_user_id=current_user.id,
            action="consent",
            resource_type="medical_image",
            resource_id=result.id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            reason_code="MEDICAL_IMAGE_NOTICE_V1",
        )
        await add_audit_log(
            db,
            actor_user_id=current_user.id,
            action="upload",
            resource_type="medical_image",
            resource_id=result.id,
            outcome=AUDIT_OUTCOME_SUCCESS,
        )
        await add_audit_log(
            db,
            actor_user_id=current_user.id,
            action="analyze",
            resource_type="medical_image",
            resource_id=result.id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            reason_code=settings.image_analysis_model,
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        await remove_image(storage_key)
        raise AppError(500, "IMAGE_SAVE_FAILED", "图片保存失败，请稍后重试") from exc
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/attachments/{attachment_id}/content",
    summary="读取当前用户仍在保留期内的规范化图片",
)
async def get_medical_image_content(
    attachment_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    row = await attachment_service.get_image_attachment(
        db, current_user.id, attachment_id
    )
    assert row.image_storage_key is not None
    assert row.image_key_ciphertext is not None
    content = await load_image(row.image_storage_key, row.image_key_ciphertext)
    return Response(
        content=content,
        media_type="image/webp",
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )