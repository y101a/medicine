"""Authenticated AI educational illustration generation endpoints."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.image_generations import (
    CreateImageGeneration,
    ImageGenerationList,
    ImageGenerationOut,
)
from app.services import image_generations as service

router = APIRouter(tags=["AI 科普配图"])


@router.post(
    "/consultations/{consultation_id}/image-generations",
    response_model=ImageGenerationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_image_generation(
    consultation_id: UUID,
    payload: CreateImageGeneration,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> ImageGenerationOut:
    result = await service.create(db, current_user.id, consultation_id, payload)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/image-generations/{image_id}",
    response_model=ImageGenerationOut,
)
async def get_image_generation(
    image_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> ImageGenerationOut:
    result = await service.get(db, current_user.id, image_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/consultations/{consultation_id}/image-generations",
    response_model=ImageGenerationList,
)
async def list_image_generations(
    consultation_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> ImageGenerationList:
    result = await service.list_for_consultation(db, current_user.id, consultation_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/image-generations/{image_id}/content")
async def get_generated_image_content(
    image_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    content = await service.content(db, current_user.id, image_id)
    return Response(
        content=content,
        media_type="image/webp",
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/image-generations/{image_id}", status_code=204)
async def delete_image_generation(
    image_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    await service.remove(db, current_user.id, image_id)
    return Response(status_code=204)
