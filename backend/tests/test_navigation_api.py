from types import SimpleNamespace

from app.ai.mcp.models import HospitalRoute, NearbyHospitalResult
from app.api.routes import navigation as navigation_route
from app.core.security import create_access_token
from app.services.auth import ACCESS_COOKIE


async def test_navigation_api_requires_consent_and_never_returns_origin(
    profile_context,
    monkeypatch,
):
    client, _, (user, _) = profile_context
    navigation_route._navigation_calls.clear()

    async def fake_nearby(latitude, longitude, **kwargs):
        assert (latitude, longitude) == (39.9, 116.4)
        assert kwargs["location_consent"] is True
        return NearbyHospitalResult(
            route_mode="driving",
            count=1,
            hospitals=[
                HospitalRoute(
                    poi_id="poi-1",
                    name="测试医院",
                    address="测试路",
                    route_distance_meters=1200,
                    route_duration_seconds=360,
                    route_mode="driving",
                    navigation_url="https://uri.amap.com/navigation?to=test",
                )
            ],
        )

    monkeypatch.setattr(navigation_route, "find_nearby_hospitals", fake_nearby)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.post(
        "/api/v1/navigation/nearby-hospitals",
        json={
            "latitude": 39.9,
            "longitude": 116.4,
            "locationConsent": True,
            "routeMode": "driving",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["routeDurationSeconds"] == 360
    assert "latitude" not in body
    assert "longitude" not in body


async def test_navigation_api_area_fallback(profile_context, monkeypatch):
    client, _, (user, _) = profile_context
    navigation_route._navigation_calls.clear()

    async def fake_area(city, **_kwargs):
        assert city == "110000"
        poi = SimpleNamespace(
            poi_id="poi-2",
            name="区域医院",
            address="区域路",
            telephone=None,
            district="海淀区",
            navigation_url="https://uri.amap.com/navigation?to=area",
        )
        return SimpleNamespace(count=1, pois=[poi])

    monkeypatch.setattr(navigation_route, "search_hospitals_by_area", fake_area)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.post(
        "/api/v1/navigation/hospitals-by-area",
        json={"city": "110000"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "area"
    assert "不能判断哪家医院最近" in response.json()["notice"]
