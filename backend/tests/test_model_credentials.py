import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, decrypt_sensitive
from app.models import UserModelCredential
from app.services import model_credentials as service
from app.services.auth import ACCESS_COOKIE

API = "/api/v1/users/me/model-credentials"


@pytest.fixture(autouse=True)
def clear_verification_rate_limit():
    service._verification_calls.clear()
    yield
    service._verification_calls.clear()


def authenticate(client, user) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))


async def test_credential_is_encrypted_masked_isolated_and_overrides_server(
    profile_context, monkeypatch
):
    client, db, (first, second) = profile_context
    settings = get_settings()
    monkeypatch.setattr(
        settings, "deepseek_api_key", SecretStr("server-deepseek-key")
    )
    verifier = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "verify_api_key", verifier)

    assert (await client.get(API)).status_code == 401
    authenticate(client, first)
    saved = await client.put(
        f"{API}/deepseek",
        json={"apiKey": "  user-deepseek-secret-1234  "},
    )
    assert saved.status_code == 200
    assert saved.json()["provider"] == "deepseek"
    assert saved.json()["maskedKey"] == "use…1234"
    assert "user-deepseek-secret-1234" not in saved.text
    verifier.assert_awaited_once_with("deepseek", "user-deepseek-secret-1234")

    row = await db.scalar(
        select(UserModelCredential).where(
            UserModelCredential.user_id == first.id,
            UserModelCredential.provider == "deepseek",
        )
    )
    assert row is not None
    assert row.api_key_ciphertext != "user-deepseek-secret-1234"
    assert decrypt_sensitive(row.api_key_ciphertext) == "user-deepseek-secret-1234"

    restored = await client.get(API)
    assert restored.status_code == 200
    assert restored.json()["items"][0]["maskedKey"] == "use…1234"
    assert "user-deepseek-secret-1234" not in restored.text

    models = (await client.get("/api/v1/models")).json()["items"]
    deepseek = next(item for item in models if item["provider"] == "deepseek")
    assert deepseek["keySource"] == "user"
    assert sum(item["isDefault"] for item in models) == 1
    resolved = await service.get_model_for_user(db, first.id, "deepseek-v4-flash")
    assert resolved.key_source == "user"
    assert resolved.api_key.get_secret_value() == "user-deepseek-secret-1234"

    client.cookies.set(ACCESS_COOKIE, create_access_token(second.id))
    assert (await client.get(API)).json() == {"items": []}
    other_models = (await client.get("/api/v1/models")).json()["items"]
    other_deepseek = next(
        item for item in other_models if item["provider"] == "deepseek"
    )
    assert other_deepseek["keySource"] == "server"

    client.cookies.set(ACCESS_COOKIE, create_access_token(first.id))
    assert (await client.delete(f"{API}/deepseek")).status_code == 204
    assert (await client.get(API)).json() == {"items": []}
    fallback_models = (await client.get("/api/v1/models")).json()["items"]
    fallback = next(
        item for item in fallback_models if item["provider"] == "deepseek"
    )
    assert fallback["keySource"] == "server"
    resolved_fallback = await service.get_model_for_user(
        db, first.id, "deepseek-v4-flash"
    )
    assert resolved_fallback.key_source == "server"
    assert (
        resolved_fallback.api_key.get_secret_value()
        == "server-deepseek-key"
    )


async def test_user_key_adds_model_when_server_key_is_absent(
    profile_context, monkeypatch
):
    client, _, (user, _) = profile_context
    settings = get_settings()
    monkeypatch.setattr(settings, "qwen_api_key", None)
    monkeypatch.setattr(service, "verify_api_key", AsyncMock(return_value=None))
    authenticate(client, user)

    before = (await client.get("/api/v1/models")).json()["items"]
    assert all(item["provider"] != "qwen" for item in before)
    assert (
        await client.put(
            f"{API}/qwen",
            json={"apiKey": "qwen-user-secret-5678"},
        )
    ).status_code == 200
    after = (await client.get("/api/v1/models")).json()["items"]
    qwen = next(item for item in after if item["provider"] == "qwen")
    assert qwen["keySource"] == "user"


async def test_invalid_or_unsupported_key_is_not_stored(
    profile_context, monkeypatch
):
    client, db, (user, _) = profile_context
    authenticate(client, user)

    async def reject_key(_provider: str, _api_key: str) -> None:
        raise AppError(
            422,
            "MODEL_CREDENTIAL_INVALID",
            "API Key 无效、无权限或当前不可用",
        )

    monkeypatch.setattr(service, "verify_api_key", reject_key)
    rejected = await client.put(
        f"{API}/deepseek",
        json={"apiKey": "invalid-secret"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "MODEL_CREDENTIAL_INVALID"
    assert (
        await db.scalar(
            select(UserModelCredential).where(
                UserModelCredential.user_id == user.id
            )
        )
        is None
    )

    unsupported = await client.put(
        f"{API}/untrusted-provider",
        json={"apiKey": "long-enough-secret"},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "MODEL_PROVIDER_UNSUPPORTED"


async def test_credential_verification_is_rate_limited(
    profile_context, monkeypatch
):
    client, _, (user, _) = profile_context
    authenticate(client, user)
    verifier = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "verify_api_key", verifier)

    for index in range(service.VERIFY_LIMIT):
        result = await client.put(
            f"{API}/deepseek",
            json={"apiKey": f"user-secret-{index:04d}"},
        )
        assert result.status_code == 200
    blocked = await client.put(
        f"{API}/deepseek",
        json={"apiKey": "user-secret-blocked"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "MODEL_CREDENTIAL_RATE_LIMITED"
    assert verifier.await_count == service.VERIFY_LIMIT


async def test_verification_uses_header_and_one_output_token_only():
    observed: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        await service.verify_api_key(
            "deepseek",
            "user-secret-header-1234",
            client=client,
        )

    assert "user-secret-header-1234" not in str(observed["url"])
    assert observed["authorization"] == "Bearer user-secret-header-1234"
    payload = observed["payload"]
    assert isinstance(payload, dict)
    assert payload["max_tokens"] == 1
    assert payload["stream"] is False


async def test_verification_rejects_provider_auth_failure():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AppError) as error:
            await service.verify_api_key(
                "deepseek",
                "invalid-user-secret",
                client=client,
            )
    assert error.value.status_code == 422
    assert error.value.code == "MODEL_CREDENTIAL_INVALID"
