"""Health record endpoints.

Registration in ``app.api.router`` is pending until the parallel session stops editing
shared files; this module is complete and importable on its own.
"""

from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.health_records import (
    HealthRecordCreate,
    HealthRecordExtractRequest,
    HealthRecordList,
    HealthRecordOnboarding,
    HealthRecordOut,
    HealthRecordSettingsOut,
    HealthRecordSettingsUpdate,
    HealthRecordUpdate,
)
from app.services import health_records as service

router = APIRouter(prefix="/health-records", tags=["健康记录"])


@router.get("/settings", response_model=HealthRecordSettingsOut, summary="采集开关与首次通知状态")
async def read_health_record_settings(
    user: CurrentUser, db: DbSession
) -> HealthRecordSettingsOut:
    return await service.settings_out(db, user.id)


@router.patch("/settings", response_model=HealthRecordSettingsOut, summary="修改采集开关/通知状态")
async def patch_health_record_settings(
    payload: HealthRecordSettingsUpdate, user: CurrentUser, db: DbSession
) -> HealthRecordSettingsOut:
    return await service.update_settings(db, user.id, payload)


@router.post("/onboarding", response_model=HealthRecordSettingsOut, summary="首次身体状况采集")
async def submit_health_record_onboarding(
    payload: HealthRecordOnboarding, user: CurrentUser, db: DbSession
) -> HealthRecordSettingsOut:
    return await service.record_onboarding(db, user.id, payload)


@router.post("/extract", summary="按单条助手回答增量更新健康记录")
async def extract_health_records(
    payload: HealthRecordExtractRequest, user: CurrentUser, db: DbSession
) -> dict[str, int]:
    stored = await service.extract_from_message(
        db, user.id, payload.consultation_id, payload.message_id
    )
    return {"stored": stored}


@router.get("", response_model=HealthRecordList, summary="健康记录列表")
async def list_health_records(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=service.MAX_LIST_ITEMS, ge=1, le=service.MAX_LIST_ITEMS),
) -> HealthRecordList:
    return await service.list_records(db, user.id, limit)


@router.post(
    "",
    response_model=HealthRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="手动新增健康记录",
)
async def create_health_record(
    payload: HealthRecordCreate, user: CurrentUser, db: DbSession
) -> HealthRecordOut:
    return await service.create_record(db, user.id, payload)


@router.patch("/{record_id}", response_model=HealthRecordOut, summary="修改健康记录")
async def patch_health_record(
    record_id: UUID, payload: HealthRecordUpdate, user: CurrentUser, db: DbSession
) -> HealthRecordOut:
    return await service.update_record(db, user.id, record_id, payload)


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除健康记录")
async def delete_health_record(record_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.delete_record(db, user.id, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)