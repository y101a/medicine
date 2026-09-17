from collections import deque
from threading import Lock
from time import monotonic

from fastapi import APIRouter

from app.ai.mcp.amap import find_nearby_hospitals, search_hospitals_by_area
from app.ai.mcp.pubmed import ExternalToolError
from app.ai.mcp.validation import ToolInputError
from app.api.dependencies import CurrentUser
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.navigation import (
    AreaHospitalsRequest,
    HospitalNavigationOut,
    HospitalNavigationResponse,
    NearbyHospitalsRequest,
)

router = APIRouter(prefix="/navigation", tags=["就医导航"])
RATE_WINDOW_SECONDS = 600
RATE_LIMIT = 6
_rate_lock = Lock()
_navigation_calls: dict[str, deque[float]] = {}


def _enforce_rate_limit(user_id: str) -> None:
    now = monotonic()
    with _rate_lock:
        calls = _navigation_calls.setdefault(user_id, deque())
        while calls and now - calls[0] >= RATE_WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= RATE_LIMIT:
            raise AppError(429, "NAVIGATION_RATE_LIMITED", "导航查询过于频繁，请稍后再试")
        calls.append(now)


def _provider_error(exc: ExternalToolError) -> AppError:
    if str(exc) == "AMAP_NOT_CONFIGURED":
        return AppError(503, "NAVIGATION_NOT_CONFIGURED", "就医导航服务尚未配置")
    if str(exc) == "AMAP_RESPONSE_INVALID":
        return AppError(502, "NAVIGATION_PROVIDER_INVALID", "地图服务返回异常，请稍后再试")
    return AppError(502, "NAVIGATION_PROVIDER_FAILED", "地图服务暂时不可用，请稍后再试")


@router.post("/nearby-hospitals", response_model=HospitalNavigationResponse)
async def nearby_hospitals(
    payload: NearbyHospitalsRequest,
    user: CurrentUser,
) -> HospitalNavigationResponse:
    _enforce_rate_limit(str(user.id))
    settings = get_settings()
    key = settings.amap_api_key.get_secret_value() if settings.amap_api_key else None
    try:
        result = await find_nearby_hospitals(
            payload.latitude,
            payload.longitude,
            route_mode=payload.route_mode,
            max_results=3,
            location_consent=payload.location_consent,
            api_key=key,
            timeout_seconds=settings.external_tool_timeout_seconds,
        )
    except ToolInputError as exc:
        raise AppError(422, "NAVIGATION_INPUT_INVALID", str(exc)) from exc
    except ExternalToolError as exc:
        raise _provider_error(exc) from exc
    return HospitalNavigationResponse(
        mode="nearby",
        route_mode=result.route_mode,
        count=result.count,
        items=[HospitalNavigationOut(**item.model_dump()) for item in result.hospitals],
        notice=result.notice,
    )


@router.post("/hospitals-by-area", response_model=HospitalNavigationResponse)
async def hospitals_by_area(
    payload: AreaHospitalsRequest,
    user: CurrentUser,
) -> HospitalNavigationResponse:
    _enforce_rate_limit(str(user.id))
    settings = get_settings()
    key = settings.amap_api_key.get_secret_value() if settings.amap_api_key else None
    try:
        result = await search_hospitals_by_area(
            payload.city,
            max_results=5,
            api_key=key,
            timeout_seconds=settings.external_tool_timeout_seconds,
        )
    except ToolInputError as exc:
        raise AppError(422, "NAVIGATION_INPUT_INVALID", str(exc)) from exc
    except ExternalToolError as exc:
        raise _provider_error(exc) from exc
    return HospitalNavigationResponse(
        mode="area",
        count=result.count,
        items=[
            HospitalNavigationOut(
                poi_id=item.poi_id,
                name=item.name,
                address=item.address,
                telephone=item.telephone,
                district=item.district,
                navigation_url=item.navigation_url or "https://uri.amap.com/",
            )
            for item in result.pois
        ],
        notice="定位未使用，结果按城市或区县返回，不能判断哪家医院最近。",
    )
