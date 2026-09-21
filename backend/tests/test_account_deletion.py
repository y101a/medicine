from uuid import UUID

from sqlalchemy import select
from test_attachments import create_consultation, upload_txt

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.models import Attachment, AuditLog, User, UserCredentials
from app.services.auth import ACCESS_COOKIE
from app.services.avatars import avatar_path


async def test_account_delete_requires_password_and_cascades_private_data(
    profile_context, tmp_path, monkeypatch
):
    client, db, (user, _) = profile_context
    password = "correct-password"
    db.add(UserCredentials(user_id=user.id, password_hash=hash_password(password)))
    await db.commit()
    monkeypatch.setattr(get_settings(), "avatar_storage_dir", str(tmp_path))
    avatar = avatar_path(user.id)
    avatar.parent.mkdir(parents=True, exist_ok=True)
    avatar.write_bytes(b"private-avatar")

    cid = await create_consultation(client, user.id)
    uploaded = await upload_txt(client, cid, "姓名：张三 检查结果需要医生结合临床判断")
    assert uploaded.status_code == 201
    attachment_id = UUID(uploaded.json()["id"])

    wrong = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"currentPassword": "wrong-password"},
    )
    assert wrong.status_code == 422
    assert wrong.json()["code"] == "ACCOUNT_PASSWORD_INVALID"
    assert await db.get(User, user.id) is not None
    assert avatar.is_file()

    deleted = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"currentPassword": password},
    )
    assert deleted.status_code == 204
    assert not avatar.exists()
    assert await db.get(User, user.id) is None
    assert await db.get(Attachment, attachment_id) is None
    set_cookie_headers = deleted.headers.get_list("set-cookie")
    assert any(ACCESS_COOKIE in header and "Max-Age=0" in header for header in set_cookie_headers)
    assert (await client.get("/api/v1/users/me")).status_code == 401

    events = (
        await db.scalars(
            select(AuditLog)
            .where(
                AuditLog.resource_type == "account",
                AuditLog.action == "delete",
            )
            .order_by(AuditLog.created_at)
        )
    ).all()
    assert [event.outcome for event in events] == ["rejected", "success"]
    assert events[0].reason_code == "ACCOUNT_PASSWORD_INVALID"
    assert events[1].actor_user_id is None


async def test_account_delete_is_rate_limited(profile_context, monkeypatch):
    from app.services import upload_limits

    client, db, (user, _) = profile_context
    db.add(UserCredentials(user_id=user.id, password_hash=hash_password("correct-password")))
    await db.commit()
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    monkeypatch.setitem(upload_limits.RESOURCE_UPLOAD_LIMITS, "account_delete", 1)

    first = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"currentPassword": "wrong-password"},
    )
    assert first.status_code == 422
    limited = await client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"currentPassword": "wrong-password"},
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "UPLOAD_RATE_LIMITED"
