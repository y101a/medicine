from fastapi import APIRouter

from app.api.routes import (
    auth,
    consultations,
    health_records,
    knowledge,
    models,
    navigation,
    users,
    voice,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(consultations.router)
api_router.include_router(models.router)
api_router.include_router(knowledge.router)
api_router.include_router(navigation.router)
api_router.include_router(health_records.router)
api_router.include_router(voice.router)


@api_router.get("/health", tags=["系统"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
