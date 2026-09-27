from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decrypt_sensitive,
    encrypt_sensitive,
    hash_password,
    sensitive_fingerprint,
)
from app.models import (
    AuditLog,
    PhoneVerificationChallenge,
    UserCredentials,
)
from app.services import phone_verification
from app.services.auth import ACCESS_COOKIE
from app.services.sms_providers import fake
from app.services.validators import mask_phone


async def test_sms_phone_validation_and_registration_requirement(profile_context):
    client, _, _ = profile_context
    invalid_phone = await client.post(
        "/api/v1/auth/phone-verifications/code",
        json={"phone": "123", "purpose": "registration"},
    )
    assert invalid_phone.status_code == 422
    assert invalid_phone.json()["code"] == "SMS_PHONE_INVALID"

    missing_verification = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "VerificationRequired",
            "realName": "测试用户",
            "phone": "13400134000",
            "idCard": "11010519491231002X",
            "gender": "private",
            "password": "123456",
        },
    )
    assert missing_verification.status_code == 422
    assert missing_verification.json()["code"] == "PHONE_VERIFICATION_REQUIRED"


async def test_existing_user_can_verify_current_phone(
    profile_context,
    monkeypatch,
):
    client, db, (user, _) = profile_context
    user.phone_fingerprint = sensitive_fingerprint("13800138000")
    await db.flush()
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    monkeypatch.setattr(phone_verification, "generate_sms_code", lambda: "482731")

    requested = await client.post("/api/v1/users/me/phone-verification/code")
    assert requested.status_code == 202
    assert set(requested.json()) == {
        "challengeId",
        "expiresInSeconds",
        "resendAfterSeconds",
    }
    confirmed = await client.post(
        "/api/v1/users/me/phone-verification/confirm",
        json={
            "challengeId": requested.json()["challengeId"],
            "code": "482731",
        },
    )
    assert confirmed.status_code == 204
    await db.refresh(user)
    assert user.phone_verified_at is not None
    assert (await client.get("/api/v1/users/me")).json()["phoneVerified"] is True


async def test_password_reset_revokes_old_access_and_refresh_sessions(
    profile_context,
    monkeypatch,
):
    client, db, (user, _) = profile_context
    phone = "13800138000"
    user.phone_fingerprint = sensitive_fingerprint(phone)
    user.phone_verified_at = datetime.now(UTC)
    user.credentials = UserCredentials(password_hash=hash_password("old-password"))
    await db.flush()
    old_access = create_access_token(user.id, user.auth_version)
    client.cookies.set(ACCESS_COOKIE, old_access)
    monkeypatch.setattr(phone_verification, "generate_sms_code", lambda: "482731")

    requested = await client.post(
        "/api/v1/auth/phone-verifications/code",
        json={"phone": phone, "purpose": "password_reset"},
    )
    assert requested.status_code == 202
    verified = await client.post(
        "/api/v1/auth/phone-verifications/verify",
        json={
            "challengeId": requested.json()["challengeId"],
            "code": "482731",
        },
    )
    assert verified.status_code == 200
    reset = await client.post(
        "/api/v1/auth/password-reset",
        json={
            "phone": phone,
            "verificationToken": verified.json()["verificationToken"],
            "newPassword": "new-password",
        },
    )
    assert reset.status_code == 204

    client.cookies.set(ACCESS_COOKIE, old_access)
    expired = await client.get("/api/v1/users/me")
    assert expired.status_code == 401
    assert expired.json()["code"] == "SESSION_EXPIRED"
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "old-password"},
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "new-password"},
        )
    ).status_code == 200


async def test_unknown_password_reset_is_decoy_and_does_not_send(
    profile_context,
    monkeypatch,
):
    client, db, _ = profile_context
    send_code = AsyncMock()
    monkeypatch.setattr(fake.FakeSmsVerificationProvider, "send_code", send_code)
    monkeypatch.setattr(phone_verification, "generate_sms_code", lambda: "482731")

    response = await client.post(
        "/api/v1/auth/phone-verifications/code",
        json={"phone": "13900139000", "purpose": "password_reset"},
    )
    assert response.status_code == 202
    send_code.assert_not_awaited()
    challenge = await db.get(
        PhoneVerificationChallenge,
        response.json()["challengeId"],
    )
    assert challenge is not None
    assert challenge.is_decoy is True
    assert challenge.code_digest != "482731"
    rejected = await client.post(
        "/api/v1/auth/phone-verifications/verify",
        json={"challengeId": response.json()["challengeId"], "code": "482731"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "SMS_CODE_INVALID"


async def test_phone_code_send_is_rate_limited_in_database(
    profile_context,
    monkeypatch,
):
    client, _, _ = profile_context
    monkeypatch.setattr(phone_verification, "generate_sms_code", lambda: "482731")
    payload = {"phone": "13700137000", "purpose": "registration"}
    assert (
        await client.post("/api/v1/auth/phone-verifications/code", json=payload)
    ).status_code == 202
    limited = await client.post("/api/v1/auth/phone-verifications/code", json=payload)
    assert limited.status_code == 429
    assert limited.json()["code"] == "SMS_RATE_LIMITED"
    assert limited.json()["details"]["retryAfterSeconds"] > 0


async def test_code_attempt_limit_invalidates_challenge(
    profile_context,
    monkeypatch,
):
    client, db, _ = profile_context
    monkeypatch.setattr(get_settings(), "sms_max_attempts", 2)
    monkeypatch.setattr(phone_verification, "generate_sms_code", lambda: "482731")
    requested = await client.post(
        "/api/v1/auth/phone-verifications/code",
        json={"phone": "13600136000", "purpose": "registration"},
    )
    challenge_id = requested.json()["challengeId"]

    first = await client.post(
        "/api/v1/auth/phone-verifications/verify",
        json={"challengeId": challenge_id, "code": "111111"},
    )
    assert first.status_code == 422
    second = await client.post(
        "/api/v1/auth/phone-verifications/verify",
        json={"challengeId": challenge_id, "code": "222222"},
    )
    assert second.status_code == 429
    assert second.json()["code"] == "SMS_ATTEMPTS_EXCEEDED"
    challenge = await db.get(PhoneVerificationChallenge, challenge_id)
    assert challenge is not None
    assert challenge.consumed_at is not None


async def test_verification_audit_contains_no_sensitive_values(
    profile_context,
    monkeypatch,
):
    client, db, _ = profile_context
    monkeypatch.setattr(phone_verification, "generate_sms_code", lambda: "482731")
    phone = "13500135000"
    requested = await client.post(
        "/api/v1/auth/phone-verifications/code",
        json={"phone": phone, "purpose": "registration"},
    )
    assert requested.status_code == 202
    events = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.resource_id == requested.json()["challengeId"]
            )
        )
    ).all()
    assert len(events) == 1
    serialized = " ".join(
        str(value)
        for event in events
        for value in (
            event.action,
            event.resource_type,
            event.reason_code,
        )
    )
    assert phone not in serialized
    assert "482731" not in serialized


async def test_phone_change_swaps_binding_after_new_number_verification(
    profile_context,
    monkeypatch,
):
    client, db, (user, other) = profile_context
    current_phone = "13800138000"
    new_phone = "13900139001"
    # fixture 只给随机指纹，换绑测试需要指纹与密文一致的当前号。
    user.phone_ciphertext = encrypt_sensitive(current_phone)
    user.phone_fingerprint = sensitive_fingerprint(current_phone)
    user.credentials = UserCredentials(password_hash=hash_password("old-password"))
    other.phone_ciphertext = encrypt_sensitive("13700137000")
    other.phone_fingerprint = sensitive_fingerprint("13700137000")
    await db.flush()

    sent: list[tuple[str, str]] = []

    async def send_code(self, *, phone, code, purpose, expires_in_seconds):
        sent.append((phone, purpose))
        return None

    monkeypatch.setattr(fake.FakeSmsVerificationProvider, "send_code", send_code)
    monkeypatch.setattr(phone_verification, "generate_sms_code", lambda: "482731")
    base = "/api/v1/users/me/phone-verification"

    anonymous = await client.post(
        f"{base}/change-code",
        json={"phone": new_phone, "currentPassword": "old-password"},
    )
    assert anonymous.status_code == 401

    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))

    wrong_password = await client.post(
        f"{base}/change-code",
        json={"phone": new_phone, "currentPassword": "wrong-password"},
    )
    assert wrong_password.status_code == 422
    assert wrong_password.json()["code"] == "ACCOUNT_PASSWORD_INVALID"
    assert sent == []

    invalid_phone = await client.post(
        f"{base}/change-code",
        json={"phone": "12345", "currentPassword": "old-password"},
    )
    assert invalid_phone.status_code == 422
    assert invalid_phone.json()["code"] == "SMS_PHONE_INVALID"

    same_phone = await client.post(
        f"{base}/change-code",
        json={"phone": current_phone, "currentPassword": "old-password"},
    )
    assert same_phone.status_code == 422
    assert same_phone.json()["code"] == "PHONE_UNCHANGED"

    taken_phone = await client.post(
        f"{base}/change-code",
        json={"phone": "13700137000", "currentPassword": "old-password"},
    )
    assert taken_phone.status_code == 409
    assert taken_phone.json()["code"] == "PHONE_EXISTS"
    assert sent == []

    requested = await client.post(
        f"{base}/change-code",
        json={"phone": new_phone, "currentPassword": "old-password"},
    )
    assert requested.status_code == 202
    assert set(requested.json()) == {
        "challengeId",
        "expiresInSeconds",
        "resendAfterSeconds",
    }
    assert sent == [(new_phone, "phone_binding")]
    challenges = (
        await db.scalars(
            select(PhoneVerificationChallenge).where(
                PhoneVerificationChallenge.user_id == user.id,
                PhoneVerificationChallenge.purpose == "phone_binding",
            )
        )
    ).all()
    assert len(challenges) == 1
    assert str(challenges[0].id) == requested.json()["challengeId"]
    assert challenges[0].is_decoy is False
    assert challenges[0].phone_fingerprint == sensitive_fingerprint(new_phone)

    # 「当前号补验证」的挑战不能被拿来换绑：两条路共用 phone_binding 用途。
    current_challenge = await client.post(f"{base}/code")
    assert current_challenge.status_code == 202
    misuse = await client.post(
        f"{base}/change",
        json={
            "phone": new_phone,
            "challengeId": current_challenge.json()["challengeId"],
            "code": "482731",
        },
    )
    assert misuse.status_code == 422
    assert misuse.json()["code"] == "SMS_CHALLENGE_INVALID"

    wrong_code = await client.post(
        f"{base}/change",
        json={
            "phone": new_phone,
            "challengeId": requested.json()["challengeId"],
            "code": "000000",
        },
    )
    assert wrong_code.status_code == 422
    assert wrong_code.json()["code"] == "SMS_CODE_INVALID"

    changed = await client.post(
        f"{base}/change",
        json={
            "phone": new_phone,
            "challengeId": requested.json()["challengeId"],
            "code": "482731",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["phoneMasked"] == mask_phone(new_phone)
    assert changed.json()["phoneVerified"] is True
    assert sent == [(new_phone, "phone_binding"), (current_phone, "phone_binding")]
    await db.refresh(user)
    assert user.phone_fingerprint == sensitive_fingerprint(new_phone)
    assert decrypt_sensitive(user.phone_ciphertext) == new_phone
    assert user.phone_verified_at is not None

    replay = await client.post(
        f"{base}/change",
        json={
            "phone": new_phone,
            "challengeId": requested.json()["challengeId"],
            "code": "482731",
        },
    )
    assert replay.status_code == 422
    assert replay.json()["code"] == "SMS_CHALLENGE_INVALID"

    events = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.actor_user_id == user.id,
                AuditLog.action == "phone_changed",
            )
        )
    ).all()
    assert [event.outcome for event in events] == ["success"]

    # 找回密码现在认新号：新号真发，旧号只给诱饵、不发任何短信。
    reset_new = await client.post(
        "/api/v1/auth/phone-verifications/code",
        json={"phone": new_phone, "purpose": "password_reset"},
    )
    assert reset_new.status_code == 202
    assert sent[-1] == (new_phone, "password_reset")
    sent_count = len(sent)
    reset_old = await client.post(
        "/api/v1/auth/phone-verifications/code",
        json={"phone": current_phone, "purpose": "password_reset"},
    )
    assert reset_old.status_code == 202
    assert len(sent) == sent_count


@pytest.mark.parametrize("environment", ["production", "PRODUCTION"])
def test_fake_sms_provider_is_rejected_in_production(environment):
    with pytest.raises(ValueError, match="非开发测试环境禁止使用模拟短信服务"):
        type(get_settings())(
            postgres_password="test",
            jwt_secret_key="x" * 32,
            field_encryption_key=get_settings().field_encryption_key,
            fingerprint_secret="x" * 32,
            app_environment=environment,
            sms_provider="fake",
        )
