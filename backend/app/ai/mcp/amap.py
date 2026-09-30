from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.ai.mcp.models import (
    AmapPoi,
    AmapPoiResult,
    HospitalRoute,
    NearbyHospitalResult,
)
from app.ai.mcp.pubmed import ExternalToolError
from app.ai.mcp.validation import (
    ToolInputError,
    validate_city,
    validate_coordinates,
    validate_department,
    validate_limit,
    validate_route_mode,
)

AMAP_SEARCH_URL = "https://restapi.amap.com/v3/place/text"
AMAP_AROUND_URL = "https://restapi.amap.com/v3/place/around"
AMAP_CONVERT_URL = "https://restapi.amap.com/v3/assistant/coordinate/convert"
AMAP_DIRECTION_URLS = {
    "driving": "https://restapi.amap.com/v3/direction/driving",
    "walking": "https://restapi.amap.com/v3/direction/walking",
}


def _amap_client(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds, connect=timeout_seconds),
        transport=httpx.AsyncHTTPTransport(retries=1),
    )


@dataclass(frozen=True, slots=True)
class _HospitalCandidate:
    poi_id: str | None
    name: str
    address: str | None
    telephone: str | None
    district: str | None
    longitude: float
    latitude: float
    straight_distance_meters: int | None


def _optional_text(value: object) -> str | None:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _coordinate(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        longitude, latitude = (float(part) for part in parts)
    except ValueError:
        return None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None
    return longitude, latitude


def _navigation_url(longitude: float, latitude: float, name: str, mode: str) -> str:
    params = urlencode(
        {
            "to": f"{longitude:.6f},{latitude:.6f},{name}",
            "mode": "car" if mode == "driving" else "walk",
            "policy": 0,
            "src": "medical_assistant",
            "coordinate": "gaode",
            "callnative": 1,
        }
    )
    return f"https://uri.amap.com/navigation?{params}"


def _provider_payload(response: httpx.Response) -> dict[str, object]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "1":
        raise ExternalToolError("AMAP_RESPONSE_INVALID")
    return payload


def _candidate(item: object, *, hospitals_only: bool = False) -> _HospitalCandidate | None:
    if not isinstance(item, dict):
        return None
    name = _optional_text(item.get("name"))
    if hospitals_only and (not name or "医院" not in name):
        return None
    coordinates = _coordinate(item.get("entr_location")) or _coordinate(item.get("location"))
    if not name or not coordinates:
        return None
    distance = _optional_text(item.get("distance"))
    try:
        distance_meters = round(float(distance)) if distance else None
    except ValueError:
        distance_meters = None
    return _HospitalCandidate(
        poi_id=_optional_text(item.get("id")),
        name=name,
        address=_optional_text(item.get("address")),
        telephone=_optional_text(item.get("tel")),
        district=_optional_text(item.get("adname")),
        longitude=coordinates[0],
        latitude=coordinates[1],
        straight_distance_meters=distance_meters,
    )


async def search_medical_pois(
    city: str,
    department: str,
    *,
    max_results: int = 5,
    api_key: str | None,
    timeout_seconds: float = 10,
    client: httpx.AsyncClient | None = None,
) -> AmapPoiResult:
    canonical_city = validate_city(city)
    canonical_department = validate_department(department)
    limit = validate_limit(max_results)
    if not api_key or not api_key.strip():
        raise ExternalToolError("AMAP_NOT_CONFIGURED")

    owns_client = client is None
    active_client = client or _amap_client(timeout_seconds)
    try:
        response = await active_client.get(
            AMAP_SEARCH_URL,
            params={
                "key": api_key,
                "keywords": canonical_department,
                "types": "090000",
                "city": canonical_city,
                "citylimit": "true",
                "extensions": "base",
                "offset": 20,
                "page": 1,
                "output": "JSON",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "1" or not isinstance(payload.get("pois"), list):
            raise ExternalToolError("AMAP_RESPONSE_INVALID")
        pois: list[AmapPoi] = []
        for item in payload["pois"][:limit]:
            if not isinstance(item, dict) or not _optional_text(item.get("name")):
                continue
            pois.append(
                AmapPoi(
                    poi_id=_optional_text(item.get("id")),
                    name=str(item["name"]).strip(),
                    address=_optional_text(item.get("address")),
                    telephone=_optional_text(item.get("tel")),
                    province=_optional_text(item.get("pname")),
                    city=_optional_text(item.get("cityname")),
                    district=_optional_text(item.get("adname")),
                    navigation_url=(
                        _navigation_url(*coordinates, str(item["name"]).strip(), "driving")
                        if (coordinates := _coordinate(item.get("location")))
                        else None
                    ),
                )
            )
        return AmapPoiResult(
            city=canonical_city,
            department=canonical_department,
            count=len(pois),
            pois=pois,
        )
    except ExternalToolError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ExternalToolError("AMAP_REQUEST_FAILED") from exc
    finally:
        if owns_client:
            await active_client.aclose()


async def search_hospitals_by_area(
    city: str,
    *,
    max_results: int = 5,
    api_key: str | None,
    timeout_seconds: float = 10,
    client: httpx.AsyncClient | None = None,
) -> AmapPoiResult:
    canonical_city = validate_city(city)
    limit = validate_limit(max_results)
    if not api_key or not api_key.strip():
        raise ExternalToolError("AMAP_NOT_CONFIGURED")
    owns_client = client is None
    active_client = client or _amap_client(timeout_seconds)
    try:
        response = await active_client.get(
            AMAP_SEARCH_URL,
            params={
                "key": api_key,
                "keywords": "医院",
                "types": "090000",
                "city": canonical_city,
                "citylimit": "true",
                "extensions": "base",
                "offset": limit,
                "page": 1,
                "output": "JSON",
            },
        )
        payload = _provider_payload(response)
        raw_pois = payload.get("pois")
        if not isinstance(raw_pois, list):
            raise ExternalToolError("AMAP_RESPONSE_INVALID")
        pois: list[AmapPoi] = []
        for item in raw_pois[:limit]:
            candidate = _candidate(item, hospitals_only=True)
            if not candidate:
                continue
            pois.append(
                AmapPoi(
                    poi_id=candidate.poi_id,
                    name=candidate.name,
                    address=candidate.address,
                    telephone=candidate.telephone,
                    city=_optional_text(item.get("cityname")),
                    district=candidate.district,
                    province=_optional_text(item.get("pname")),
                    navigation_url=_navigation_url(
                        candidate.longitude,
                        candidate.latitude,
                        candidate.name,
                        "driving",
                    ),
                )
            )
        return AmapPoiResult(
            city=canonical_city,
            department="医院",
            count=len(pois),
            pois=pois,
        )
    except ExternalToolError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ExternalToolError("AMAP_REQUEST_FAILED") from exc
    finally:
        if owns_client:
            await active_client.aclose()


async def find_nearby_hospitals(
    latitude: float,
    longitude: float,
    *,
    route_mode: str = "driving",
    max_results: int = 3,
    location_consent: bool,
    api_key: str | None,
    timeout_seconds: float = 10,
    client: httpx.AsyncClient | None = None,
) -> NearbyHospitalResult:
    if not location_consent:
        raise ToolInputError("使用精确位置前必须取得用户本次明确授权")
    safe_latitude, safe_longitude = validate_coordinates(latitude, longitude)
    mode = validate_route_mode(route_mode)
    limit = validate_limit(max_results)
    if limit > 3:
        raise ToolInputError("为控制个人配额，附近医院每次最多比较 3 家")
    if not api_key or not api_key.strip():
        raise ExternalToolError("AMAP_NOT_CONFIGURED")

    owns_client = client is None
    active_client = client or _amap_client(timeout_seconds)
    try:
        request_timeout = timeout_seconds
        gps_location = f"{safe_longitude:.6f},{safe_latitude:.6f}"
        convert_payload = _provider_payload(
            await active_client.get(
                AMAP_CONVERT_URL,
                params={
                    "key": api_key,
                    "locations": gps_location,
                    "coordsys": "gps",
                    "output": "JSON",
                },
                timeout=request_timeout,
            )
        )
        converted = _coordinate(convert_payload.get("locations"))
        if not converted:
            raise ExternalToolError("AMAP_RESPONSE_INVALID")
        origin = f"{converted[0]:.6f},{converted[1]:.6f}"

        nearby_payload = _provider_payload(
            await active_client.get(
                AMAP_AROUND_URL,
                params={
                    "key": api_key,
                    "location": origin,
                    "keywords": "医院",
                    "types": "090000",
                    "radius": 20000,
                    "sortrule": "distance",
                    "extensions": "all",
                    "offset": 15,
                    "page": 1,
                    "output": "JSON",
                },
                timeout=request_timeout,
            )
        )
        raw_pois = nearby_payload.get("pois")
        if not isinstance(raw_pois, list):
            raise ExternalToolError("AMAP_RESPONSE_INVALID")
        candidates = [
            value for item in raw_pois if (value := _candidate(item, hospitals_only=True))
        ][:limit]
        routes: list[HospitalRoute] = []
        for hospital in candidates:
            destination = f"{hospital.longitude:.6f},{hospital.latitude:.6f}"
            params: dict[str, object] = {
                "key": api_key,
                "origin": origin,
                "destination": destination,
                "output": "JSON",
            }
            if mode == "driving":
                params["strategy"] = 10
                if hospital.poi_id:
                    params["destinationid"] = hospital.poi_id
            distance: int | None = None
            duration: int | None = None
            try:
                route_payload = _provider_payload(
                    await active_client.get(
                        AMAP_DIRECTION_URLS[mode],
                        params=params,
                        timeout=request_timeout,
                    )
                )
                route = route_payload.get("route")
                paths = route.get("paths") if isinstance(route, dict) else None
                parsed_paths: list[tuple[int, int]] = []
                if isinstance(paths, list):
                    for path in paths:
                        if not isinstance(path, dict):
                            continue
                        try:
                            parsed_paths.append(
                                (
                                    int(float(str(path["duration"]))),
                                    int(float(str(path["distance"]))),
                                )
                            )
                        except (KeyError, TypeError, ValueError):
                            continue
                if parsed_paths:
                    duration, distance = min(parsed_paths)
            except (ExternalToolError, httpx.HTTPError):
                # A route failure must not discard a successful nearby-hospital
                # lookup. Return the candidate with an explicit approximate state.
                pass
            routes.append(
                HospitalRoute(
                    poi_id=hospital.poi_id,
                    name=hospital.name,
                    address=hospital.address,
                    telephone=hospital.telephone,
                    district=hospital.district,
                    straight_distance_meters=hospital.straight_distance_meters,
                    route_distance_meters=distance,
                    route_duration_seconds=duration,
                    route_mode=mode,
                    navigation_url=_navigation_url(
                        hospital.longitude,
                        hospital.latitude,
                        hospital.name,
                        mode,
                    ),
                )
            )
        routes.sort(
            key=lambda item: (
                item.route_duration_seconds is None,
                item.route_duration_seconds
                if item.route_duration_seconds is not None
                else (item.straight_distance_meters or 999999999),
            )
        )
        notice = (
            "按高德预计路线时间排序，仅供就医查找参考；最近不等于最适合。危急情况请立即拨打 120。"
        )
        if routes and all(item.route_duration_seconds is None for item in routes):
            notice = (
                "路线服务暂时不可用，当前仅按直线距离排序；点击导航后由高德重新规划。"
                "危急情况请立即拨打 120。"
            )
        elif any(item.route_duration_seconds is None for item in routes):
            notice = (
                "优先展示已取得的路线时间，部分医院仅有直线距离；最近不等于最适合。"
                "危急情况请立即拨打 120。"
            )
        return NearbyHospitalResult(
            route_mode=mode,
            count=len(routes),
            hospitals=routes,
            notice=notice,
        )
    except (ExternalToolError, ToolInputError):
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ExternalToolError("AMAP_REQUEST_FAILED") from exc
    finally:
        if owns_client:
            await active_client.aclose()
