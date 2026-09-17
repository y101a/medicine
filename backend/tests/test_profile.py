from io import BytesIO
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import create_access_token, decrypt_sensitive, encrypt_sensitive
from app.db.session import get_db
from app.main import app
from app.models import Gender, User
from app.services.auth import ACCESS_COOKIE


@pytest.fixture
async def profile_context():
    test_engine = create_async_engine(get_settings().database_url)
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            users = []
            for name in ("测试甲", "测试乙"):
                suffix = uuid4().hex
                user = User(
                    username=suffix[:16],
                    username_normalized=suffix[:16],
                    real_name_ciphertext=encrypt_sensitive(name),
                    phone_ciphertext=encrypt_sensitive("13800138000"),
                    phone_fingerprint=suffix,
                    id_card_ciphertext=encrypt_sensitive("11010519491231002X"),
                    id_card_fingerprint=suffix,
                    gender=Gender.PRIVATE,
                )
                db.add(user)
                users.append(user)
            await db.flush()

            async def override_db():
                yield db

            app.dependency_overrides[get_db] = override_db
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    yield client, db, users
            finally:
                app.dependency_overrides.pop(get_db, None)
        await transaction.rollback()
    await test_engine.dispose()


async def test_profile_update_and_user_isolation(profile_context):
    client, db, (first, second) = profile_context
    assert (await client.patch("/api/v1/users/me", json={"gender": "male"})).status_code == 401
    client.cookies.set(ACCESS_COOKIE, create_access_token(first.id))
    before = (await client.get("/api/v1/users/me")).json()
    result = await client.patch("/api/v1/users/me", json={"realName": "  李明  "})
    assert result.status_code == 200
    assert result.json() == {**before, "realName": "李明"}
    await db.refresh(first)
    assert first.real_name_ciphertext != "李明"
    assert decrypt_sensitive(first.real_name_ciphertext) == "李明"
    assert (await client.get("/api/v1/users/me")).json()["realName"] == "李明"

    for gender in ("male", "female", "private"):
        result = await client.patch("/api/v1/users/me", json={"gender": gender})
        assert result.status_code == 200
        assert result.json()["gender"] == gender
        assert result.json()["realName"] == "李明"
    result = await client.patch("/api/v1/users/me", json={"realName": "王芳", "gender": "female"})
    assert result.status_code == 200
    assert result.json()["realName"] == "王芳"
    assert result.json()["gender"] == "female"
    client.cookies.set(ACCESS_COOKIE, create_access_token(second.id))
    other = (await client.get("/api/v1/users/me")).json()
    assert other["realName"] == "测试乙"
    assert other["gender"] == "private"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"realName": None},
        {"gender": None},
        {"realName": ""},
        {"realName": "  李  "},
        {"realName": "李" * 21},
        {"realName": "姓名123"},
        {"gender": "unknown"},
        {"role": "admin"},
        {"id": str(uuid4())},
        {"user_id": str(uuid4())},
        {"username": "newname"},
        {"phone": "13900139000"},
        {"idCard": "11010519491231002X"},
        {"registeredAt": "2020-01-01"},
        {"realName": "李明", "role": "admin"},
    ],
)
async def test_invalid_profile_changes_are_atomic(profile_context, payload):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    before = (await client.get("/api/v1/users/me")).json()
    result = await client.patch("/api/v1/users/me", json=payload)
    assert result.status_code == 422
    assert result.json()["code"] == "VALIDATION_ERROR"
    assert (await client.get("/api/v1/users/me")).json() == before


def avatar_bytes(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (800, 600), color).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_avatar_upload_replace_and_user_isolation(profile_context, tmp_path, monkeypatch):
    client, _, (first, second) = profile_context
    monkeypatch.setattr(get_settings(), "avatar_storage_dir", str(tmp_path))
    endpoint = "/api/v1/users/me/avatar"

    assert (await client.get(endpoint)).status_code == 401
    assert (
        await client.put(
            endpoint,
            files={"avatar": ("avatar.png", avatar_bytes("blue"), "image/png")},
        )
    ).status_code == 401

    client.cookies.set(ACCESS_COOKIE, create_access_token(first.id))
    uploaded = await client.put(
        endpoint,
        files={"avatar": ("avatar.png", avatar_bytes("blue"), "image/png")},
    )
    assert uploaded.status_code == 200
    restored = await client.get(endpoint)
    assert restored.status_code == 200
    assert restored.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(restored.content)) as image:
        assert image.size == (512, 512)
        assert image.format == "WEBP"

    first_avatar = restored.content
    replaced = await client.put(
        endpoint,
        files={"avatar": ("replacement.jpg", avatar_bytes("red"), "image/jpeg")},
    )
    assert replaced.status_code == 200
    assert (await client.get(endpoint)).content != first_avatar

    client.cookies.set(ACCESS_COOKIE, create_access_token(second.id))
    assert (await client.get(endpoint)).status_code == 404


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "status", "code"),
    [
        ("avatar.gif", b"GIF89a", "image/gif", 415, "AVATAR_TYPE_NOT_ALLOWED"),
        ("avatar.png", b"not-an-image", "image/png", 422, "AVATAR_INVALID"),
        ("avatar.png", b"x" * (3 * 1024 * 1024 + 1), "image/png", 413, "AVATAR_TOO_LARGE"),
    ],
    ids=["unsupported-type", "corrupt-image", "too-large"],
)
async def test_invalid_avatar_is_rejected(
    profile_context, tmp_path, monkeypatch, filename, content, content_type, status, code
):
    client, _, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "avatar_storage_dir", str(tmp_path))
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.put(
        "/api/v1/users/me/avatar",
        files={"avatar": (filename, content, content_type)},
    )
    assert response.status_code == status
    assert response.json()["code"] == code
    assert list(tmp_path.iterdir()) == []
