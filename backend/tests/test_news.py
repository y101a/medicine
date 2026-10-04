from app.core.security import create_access_token
from app.services.auth import ACCESS_COOKIE


async def test_news_shell_requires_login_and_never_invents_items(profile_context):
    client, _db, users = profile_context
    endpoint = "/api/v1/news"
    assert (await client.get(endpoint)).status_code == 401

    client.cookies.set(ACCESS_COOKIE, create_access_token(users[0].id))
    for category in ("all", "wellness", "fitness", "disease", "medication"):
        response = await client.get(endpoint, params={"category": category})
        assert response.status_code == 200
        assert response.json() == {
            "category": category,
            "status": "sources_not_connected",
            "asOf": None,
            "items": [],
            "tips": [],
        }

    assert (await client.get(endpoint, params={"category": "invalid"})).status_code == 422
