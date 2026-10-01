import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.private_knowledge import (
    CreatePrivateKnowledgeCollection,
    PrivateKnowledgeCollectionList,
    PrivateKnowledgeCollectionOut,
    PrivateKnowledgeDocumentList,
    PrivateKnowledgeDocumentOut,
    PrivateKnowledgeSearchOut,
    PrivateKnowledgeSearchRequest,
    UpdatePrivateKnowledgeCollection,
)
from app.services import private_knowledge as service
from app.services.audit_logs import AUDIT_OUTCOME_REJECTED, AUDIT_OUTCOME_SUCCESS, add_audit_log
from app.services.document_extract import extract_document
from app.services.upload_limits import enforce_upload_rate_limit

router = APIRouter(prefix="/private-knowledge", tags=["用户专属知识库"])
logger = logging.getLogger(__name__)
NOTICE_VERSION = "private-knowledge-upload-v1"


async def _audit_rejection(db: DbSession, user: CurrentUser, code: str) -> None:
    try:
        await add_audit_log(
            db,
            actor_user_id=user.id,
            action="upload",
            resource_type="private_knowledge_document",
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code=code[:64],
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Failed to persist private knowledge upload rejection audit")


@router.post("/collections", response_model=PrivateKnowledgeCollectionOut, status_code=201)
async def create_collection(
    payload: CreatePrivateKnowledgeCollection,
    user: CurrentUser,
    db: DbSession,
    response: Response,
) -> PrivateKnowledgeCollectionOut:
    result = await service.create_collection(db, user.id, payload.name, payload.description)
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="create",
        resource_type="private_knowledge_collection",
        resource_id=result.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/collections", response_model=PrivateKnowledgeCollectionList)
async def get_collections(
    user: CurrentUser, db: DbSession, response: Response
) -> PrivateKnowledgeCollectionList:
    result = await service.list_collections(db, user.id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.patch("/collections/{collection_id}", response_model=PrivateKnowledgeCollectionOut)
async def update_collection(
    collection_id: UUID,
    payload: UpdatePrivateKnowledgeCollection,
    user: CurrentUser,
    db: DbSession,
    response: Response,
) -> PrivateKnowledgeCollectionOut:
    result = await service.update_collection(
        db,
        user.id,
        collection_id,
        payload.name,
        payload.description,
        update_description="description" in payload.model_fields_set,
    )
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="update",
        resource_type="private_knowledge_collection",
        resource_id=collection_id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete("/collections/{collection_id}", status_code=204)
async def remove_collection(collection_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.delete_collection(db, user.id, collection_id)
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="delete",
        resource_type="private_knowledge_collection",
        resource_id=collection_id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    return Response(status_code=204)


@router.post(
    "/collections/{collection_id}/documents",
    response_model=PrivateKnowledgeDocumentOut,
    status_code=201,
)
async def upload_document(
    collection_id: UUID,
    user: CurrentUser,
    db: DbSession,
    response: Response,
    file: Annotated[UploadFile, File()],
    notice_accepted: Annotated[bool, Form(alias="noticeAccepted")] = False,
    notice_version: Annotated[str, Form(alias="noticeVersion")] = "",
) -> PrivateKnowledgeDocumentOut:
    settings = get_settings()
    try:
        enforce_upload_rate_limit(user.id, "private_knowledge_document")
        if not notice_accepted or notice_version != NOTICE_VERSION:
            raise AppError(
                422,
                "PRIVATE_KNOWLEDGE_NOTICE_REQUIRED",
                "上传前请确认私人资料处理和模型使用说明",
            )
        await service.validate_collection_ids(db, user.id, [collection_id])
        document = await extract_document(
            file,
            max_bytes=settings.attachment_max_bytes,
            max_pages=settings.attachment_max_pages,
            max_chars=settings.attachment_max_chars,
            max_chunk_chars=settings.attachment_chunk_chars,
            timeout_seconds=settings.attachment_parse_timeout_seconds,
        )
        result = await service.create_document(db, user.id, collection_id, document)
    except AppError as exc:
        mapping = {
            "FILE_TYPE_NOT_ALLOWED": "PRIVATE_KNOWLEDGE_DOCUMENT_UNSUPPORTED",
            "FILE_TOO_LARGE": "PRIVATE_KNOWLEDGE_DOCUMENT_TOO_LARGE",
            "FILE_PARSE_FAILED": "PRIVATE_KNOWLEDGE_PARSE_FAILED",
            "FILE_PARSE_TIMEOUT": "PRIVATE_KNOWLEDGE_PARSE_FAILED",
            "FILE_NO_TEXT": "PRIVATE_KNOWLEDGE_PARSE_FAILED",
            "FILE_ENCRYPTED": "PRIVATE_KNOWLEDGE_PARSE_FAILED",
            "FILE_PAGE_LIMIT": "PRIVATE_KNOWLEDGE_PARSE_FAILED",
            "FILE_TEXT_TOO_LARGE": "PRIVATE_KNOWLEDGE_PARSE_FAILED",
            "FILE_ZIP_UNSAFE": "PRIVATE_KNOWLEDGE_PARSE_FAILED",
            "UPLOAD_RATE_LIMITED": "PRIVATE_KNOWLEDGE_RATE_LIMITED",
        }
        code = mapping.get(exc.code, exc.code)
        if exc.code != "UPLOAD_RATE_LIMITED":
            await _audit_rejection(db, user, code)
        if code != exc.code:
            raise AppError(exc.status_code, code, exc.message, exc.details) from exc
        raise
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="consent",
        resource_type="private_knowledge_document",
        resource_id=result.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
        reason_code="PRIVATE_KNOWLEDGE_UPLOAD_NOTICE_V1",
    )
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="upload",
        resource_type="private_knowledge_document",
        resource_id=result.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/collections/{collection_id}/documents", response_model=PrivateKnowledgeDocumentList)
async def get_documents(
    collection_id: UUID,
    user: CurrentUser,
    db: DbSession,
    response: Response,
) -> PrivateKnowledgeDocumentList:
    result = await service.list_documents(db, user.id, collection_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/documents/{document_id}", response_model=PrivateKnowledgeDocumentOut)
async def get_document(
    document_id: UUID, user: CurrentUser, db: DbSession, response: Response
) -> PrivateKnowledgeDocumentOut:
    result = await service.get_document(db, user.id, document_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/documents/{document_id}/retry", response_model=PrivateKnowledgeDocumentOut)
async def retry_document(
    document_id: UUID, user: CurrentUser, db: DbSession, response: Response
) -> PrivateKnowledgeDocumentOut:
    result = await service.retry_document(db, user.id, document_id)
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="reindex",
        resource_type="private_knowledge_document",
        resource_id=document_id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete("/documents/{document_id}", status_code=204)
async def remove_document(document_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.delete_document(db, user.id, document_id)
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="delete",
        resource_type="private_knowledge_document",
        resource_id=document_id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/search", response_model=PrivateKnowledgeSearchOut)
async def search_private_documents(
    payload: PrivateKnowledgeSearchRequest,
    user: CurrentUser,
    db: DbSession,
    response: Response,
) -> PrivateKnowledgeSearchOut:
    result = await service.search(
        db,
        user_id=user.id,
        collection_ids=payload.collection_ids,
        query=payload.query,
        limit=payload.limit,
    )
    response.headers["Cache-Control"] = "no-store"
    return result
