import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal, engine
from app.main import app
from app.models import User


async def remove_test_user(username_normalized: str) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.username_normalized == username_normalized))
        await db.commit()
    await engine.dispose()


def test_complete_auth_flow() -> None:
    username = f"Test{uuid4().hex[:8]}"
    username_normalized = username.casefold()
    payload = {
        "username": username,
        "realName": "测试用户",
        "phone": "13800138000",
        "idCard": "11010519491231002X",
        "gender": "private",
        "password": "123456",
    }

    try:
        with TestClient(app) as client:
            register = client.post("/api/v1/auth/register", json=payload)
            assert register.status_code == 201
            assert register.json()["user"]["realName"] == "测试用户"
            assert register.json()["user"]["phoneMasked"] == "138****8000"
            assert "medical_access_token" not in register.cookies

            duplicate = client.post("/api/v1/auth/register", json=payload)
            assert duplicate.status_code == 409

            invalid_login = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": "wrong-password"},
            )
            assert invalid_login.status_code == 401

            login = client.post(
                "/api/v1/auth/login",
                json={"username": username.swapcase(), "password": "123456"},
            )
            assert login.status_code == 200
            assert "medical_access_token" in client.cookies
            assert "medical_refresh_token" in client.cookies

            current_user = client.get("/api/v1/users/me")
            assert current_user.status_code == 200
            assert current_user.json()["username"] == username

            refresh = client.post("/api/v1/auth/refresh")
            assert refresh.status_code == 200

            logout = client.post("/api/v1/auth/logout")
            assert logout.status_code == 204
            assert client.get("/api/v1/users/me").status_code == 401
    finally:
        asyncio.run(remove_test_user(username_normalized))


def test_registration_validation_error_shape() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/auth/register", json={"username": "a"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["message"] == "提交的信息校验未通过"
