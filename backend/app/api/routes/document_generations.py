"""Authenticated AI educational DOCX/PPTX generation endpoints."""

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.document_generations import (
    CreateDocumentGeneration,
    DocumentGenerationList,
    DocumentGenerationOut,
)
from app.services import document_generations as service

router = APIRouter(tags=["AI 科普文档"])


@router.post(
    "/consultations/{consultation_id}/document-generations",
    response_model=DocumentGenerationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_document_generation(
    consultation_id: UUID,
    payload: CreateDocumentGeneration,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> DocumentGenerationOut:
    result = await service.create(db, current_user.id, consultation_id, payload)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/document-generations/{generation_id}", response_model=DocumentGenerationOut)
async def get_document_generation(
    generation_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> DocumentGenerationOut:
    result = await service.get(db, current_user.id, generation_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/consultations/{consultation_id}/document-generations",
    response_model=DocumentGenerationList,
)
async def list_document_generations(
    consultation_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> DocumentGenerationList:
    result = await service.list_for_consultation(db, current_user.id, consultation_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/document-generations/{generation_id}/files/{file_id}/content")
async def get_generated_document_content(
    generation_id: UUID,
    file_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    content, file = await service.content(db, current_user.id, generation_id, file_id)
    filename = quote(f"AI医学科普-{file.created_at:%Y%m%d}.{file.format}")
    return Response(
        content=content,
        media_type=file.mime_type,
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/document-generations/{generation_id}", status_code=204)
async def delete_document_generation(
    generation_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    await service.remove(db, current_user.id, generation_id)
    return Response(status_code=204)
