import hashlib
import hmac
import math
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import (
    decrypt_sensitive,
    encrypt_sensitive,
    hash_password,
    sensitive_fingerprint,
    verify_password,
)
from app.models import (
    AuthSession,
    PhoneVerificationChallenge,
    PhoneVerificationPurpose,
    User,
)
from app.schemas.phone_verification import (
    PhoneChallengeOut,
    PhoneVerificationTokenOut,
    normalize_mainland_phone,
)
from app.services.audit_logs import (
    AUDIT_OUTCOME_REJECTED,
    AUDIT_OUTCOME_SUCCESS,
    add_audit_log,
)
from app.services.sms_providers import get_sms_provider


def generate_sms_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _sms_secret() -> bytes:
    settings = get_settings()
    configured = settings.sms_code_secret
    value = configured.get_secret_value() if configured is not None else settings.fingerprint_secret
    return value.encode("utf-8")


def _digest(value: str, *, scope: str) -> str:
    return hmac.new(
        _sms_secret(),
        f"{scope}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _code_digest(challenge_id: UUID, code: str) -> str:
    return _digest(code, scope=f"sms-code:{challenge_id}")


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ip_fingerprint(ip_address: str | None) -> str:
    return _digest(ip_address or "unknown", scope="sms-ip")


def _seconds_until(target: datetime, now: datetime) -> int:
    return max(1, math.ceil((target - now).total_seconds()))


async def _count_since(
    db: AsyncSession,
    *,
    column,
    value: str,
    since: datetime,
) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(PhoneVerificationChallenge)
            .where(column == value, PhoneVerificationChallenge.created_at >= since)
        )
        or 0
    )


async def _enforce_send_limits(
    db: AsyncSession,
    *,
    phone_fingerprint: str,
    ip_fingerprint: str,
    purpose: str,
    now: datetime,
) -> None:
    settings = get_settings()
    latest = await db.scalar(
        select(PhoneVerificationChallenge)
        .where(
            PhoneVerificationChallenge.phone_fingerprint == phone_fingerprint,
            PhoneVerificationChallenge.purpose == purpose,
        )
        .order_by(PhoneVerificationChallenge.created_at.desc())
        .limit(1)
    )
    if latest and latest.resend_available_at > now:
        raise AppError(
            429,
            "SMS_RATE_LIMITED",
            "验证码发送过于频繁，请稍后再试",
            {"retryAfterSeconds": _seconds_until(latest.resend_available_at, now)},
        )

    windows = (
        (
            PhoneVerificationChallenge.phone_fingerprint,
            phone_fingerprint,
            now - timedelta(hours=1),
            settings.sms_limit_phone_hourly,
            3600,
        ),
        (
            PhoneVerificationChallenge.phone_fingerprint,
            phone_fingerprint,
            now - timedelta(days=1),
            settings.sms_limit_phone_daily,
            86400,
        ),
        (
            PhoneVerificationChallenge.request_ip_fingerprint,
            ip_fingerprint,
            now - timedelta(minutes=10),
            settings.sms_limit_ip_10m,
            600,
        ),
        (
            PhoneVerificationChallenge.request_ip_fingerprint,
            ip_fingerprint,
            now - timedelta(days=1),
            settings.sms_limit_ip_daily,
            86400,
        ),
    )
    for column, value, since, limit, retry_seconds in windows:
        if await _count_since(db, column=column, value=value, since=since) >= limit:
            raise AppError(
                429,
                "SMS_RATE_LIMITED",
                "验证码发送过于频繁，请稍后再试",
                {"retryAfterSeconds": retry_seconds},
            )


async def _invalidate_previous_challenges(
    db: AsyncSession,
    *,
    phone_fingerprint: str,
    purpose: str,
    now: datetime,
) -> None:
    await db.execute(
        update(PhoneVerificationChallenge)
        .where(
            PhoneVerificationChallenge.phone_fingerprint == phone_fingerprint,
            PhoneVerificationChallenge.purpose == purpose,
            PhoneVerificationChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )


async def _delete_expired_challenges(db: AsyncSession, now: datetime) -> None:
    await db.execute(
        delete(PhoneVerificationChallenge).where(
            PhoneVerificationChallenge.expires_at < now - timedelta(days=1)
        )
    )


async def request_public_code(
    db: AsyncSession,
    *,
    phone: str,
    purpose: PhoneVerificationPurpose,
    ip_address: str | None,
) -> PhoneChallengeOut:
    if purpose not in {
        PhoneVerificationPurpose.REGISTRATION,
        PhoneVerificationPurpose.PASSWORD_RESET,
    }:
        raise ValueError("Public phone verification purpose is not supported")

    now = datetime.now(UTC)
    settings = get_settings()
    phone_fingerprint = sensitive_fingerprint(phone)
    ip_fingerprint = _ip_fingerprint(ip_address)
    await _delete_expired_challenges(db, now)
    await _enforce_send_limits(
        db,
        phone_fingerprint=phone_fingerprint,
        ip_fingerprint=ip_fingerprint,
        purpose=purpose.value,
        now=now,
    )
    user = await db.scalar(select(User).where(User.phone_fingerprint == phone_fingerprint))
    send_real_code = (
        purpose == PhoneVerificationPurpose.REGISTRATION
        and user is None
        or purpose == PhoneVerificationPurpose.PASSWORD_RESET
        and user is not None
        and user.phone_verified_at is not None
    )
    await _invalidate_previous_challenges(
        db,
        phone_fingerprint=phone_fingerprint,
        purpose=purpose.value,
        now=now,
    )

    challenge_id = secrets.token_hex(16)
    challenge_uuid = UUID(challenge_id)
    code = generate_sms_code()
    challenge = PhoneVerificationChallenge(
        id=challenge_uuid,
        user_id=user.id if send_real_code and user is not None else None,
        phone_fingerprint=phone_fingerprint,
        purpose=purpose.value,
        provider=get_settings().sms_provider,
        code_digest=_code_digest(challenge_uuid, code),
        request_ip_fingerprint=ip_fingerprint,
        is_decoy=not send_real_code,
        max_attempts=settings.sms_max_attempts,
        expires_at=now + timedelta(seconds=settings.sms_code_expire_seconds),
        resend_available_at=now + timedelta(seconds=settings.sms_resend_seconds),
    )
    db.add(challenge)
    await db.flush()

    if send_real_code:
        provider = get_sms_provider()
        challenge.provider = provider.name
        challenge.provider_reference = await provider.send_code(
            phone=phone,
            code=code,
            purpose=purpose.value,
            expires_in_seconds=settings.sms_code_expire_seconds,
        )

    await add_audit_log(
        db,
        actor_user_id=challenge.user_id,
        action="sms_code_requested",
        resource_type="phone_verification",
        resource_id=challenge.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
        reason_code="DECOY" if challenge.is_decoy else None,
    )
    await db.commit()
    return PhoneChallengeOut(
        challenge_id=challenge.id,
        expires_in_seconds=settings.sms_code_expire_seconds,
        resend_after_seconds=settings.sms_resend_seconds,
    )


async def _locked_challenge(
    db: AsyncSession,
    challenge_id: UUID,
) -> PhoneVerificationChallenge | None:
    return await db.scalar(
        select(PhoneVerificationChallenge)
        .where(PhoneVerificationChallenge.id == challenge_id)
        .with_for_update()
    )


async def _reject_code(
    db: AsyncSession,
    challenge: PhoneVerificationChallenge,
    *,
    code: str,
    status_code: int = 422,
) -> None:
    challenge.attempt_count += 1
    exceeded = challenge.attempt_count >= challenge.max_attempts
    if exceeded:
        challenge.consumed_at = datetime.now(UTC)
    reason = "SMS_ATTEMPTS_EXCEEDED" if exceeded else code
    await add_audit_log(
        db,
        actor_user_id=challenge.user_id,
        action="sms_code_verified",
        resource_type="phone_verification",
        resource_id=challenge.id,
        outcome=AUDIT_OUTCOME_REJECTED,
        reason_code=reason,
    )
    await db.commit()
    if exceeded:
        raise AppError(429, reason, "验证码错误次数过多，请重新获取")
    raise AppError(status_code, code, "验证码错误或已失效，请重新获取")


async def verify_public_code(
    db: AsyncSession,
    *,
    challenge_id: UUID,
    code: str,
) -> PhoneVerificationTokenOut:
    challenge = await _locked_challenge(db, challenge_id)
    if (
        challenge is None
        or challenge.purpose
        not in {
            PhoneVerificationPurpose.REGISTRATION.value,
            PhoneVerificationPurpose.PASSWORD_RESET.value,
        }
    ):
        raise AppError(422, "SMS_CHALLENGE_INVALID", "验证码请求无效，请重新获取")

    now = datetime.now(UTC)
    if challenge.consumed_at is not None or challenge.verified_at is not None:
        raise AppError(422, "SMS_CHALLENGE_INVALID", "验证码请求无效，请重新获取")
    if challenge.expires_at <= now:
        challenge.consumed_at = now
        await db.commit()
        raise AppError(422, "SMS_CODE_EXPIRED", "验证码已过期，请重新获取")

    supplied_digest = _code_digest(challenge.id, code)
    valid = hmac.compare_digest(supplied_digest, challenge.code_digest)
    if not valid or challenge.is_decoy:
        await _reject_code(db, challenge, code="SMS_CODE_INVALID")

    token = secrets.token_urlsafe(48)
    challenge.verified_at = now
    challenge.verification_token_hash = _token_digest(token)
    challenge.verification_token_expires_at = now + timedelta(
        seconds=get_settings().sms_token_expire_seconds
    )
    await add_audit_log(
        db,
        actor_user_id=challenge.user_id,
        action="sms_code_verified",
        resource_type="phone_verification",
        resource_id=challenge.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    return PhoneVerificationTokenOut(
        verification_token=token,
        expires_in_seconds=get_settings().sms_token_expire_seconds,
    )


async def consume_registration_token(
    db: AsyncSession,
    *,
    token: str,
    phone_fingerprint: str,
) -> PhoneVerificationChallenge:
    now = datetime.now(UTC)
    challenge = await db.scalar(
        select(PhoneVerificationChallenge)
        .where(
            PhoneVerificationChallenge.verification_token_hash
            == _token_digest(token)
        )
        .with_for_update()
    )
    if (
        challenge is None
        or challenge.purpose != PhoneVerificationPurpose.REGISTRATION.value
        or challenge.phone_fingerprint != phone_fingerprint
        or challenge.verified_at is None
        or challenge.verification_token_expires_at is None
        or challenge.verification_token_expires_at <= now
        or challenge.consumed_at is not None
        or challenge.is_decoy
    ):
        raise AppError(
            422,
            "PHONE_VERIFICATION_TOKEN_INVALID",
            "手机号验证已失效，请重新获取验证码",
        )
    return challenge


async def reset_password(
    db: AsyncSession,
    *,
    phone: str,
    verification_token: str,
    new_password: str,
) -> None:
    now = datetime.now(UTC)
    phone_fingerprint = sensitive_fingerprint(phone)
    challenge = await db.scalar(
        select(PhoneVerificationChallenge)
        .where(
            PhoneVerificationChallenge.verification_token_hash
            == _token_digest(verification_token)
        )
        .with_for_update()
    )
    if (
        challenge is None
        or challenge.purpose != PhoneVerificationPurpose.PASSWORD_RESET.value
        or challenge.phone_fingerprint != phone_fingerprint
        or challenge.user_id is None
        or challenge.verified_at is None
        or challenge.verification_token_expires_at is None
        or challenge.verification_token_expires_at <= now
        or challenge.consumed_at is not None
        or challenge.is_decoy
    ):
        raise AppError(
            422,
            "PHONE_VERIFICATION_TOKEN_INVALID",
            "手机号验证已失效，请重新获取验证码",
        )

    user = await db.scalar(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.id == challenge.user_id)
        .with_for_update()
    )
    if user is None or user.credentials is None:
        raise AppError(
            422,
            "PHONE_VERIFICATION_TOKEN_INVALID",
            "手机号验证已失效，请重新获取验证码",
        )

    challenge.consumed_at = now
    user.credentials.password_hash = hash_password(new_password)
    user.credentials.password_changed_at = now
    user.credentials.failed_attempts = 0
    user.credentials.locked_until = None
    user.auth_version += 1
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="password_reset",
        resource_type="account",
        resource_id=user.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()


async def request_current_phone_code(
    db: AsyncSession,
    *,
    user: User,
    ip_address: str | None,
) -> PhoneChallengeOut:
    now = datetime.now(UTC)
    settings = get_settings()
    phone = decrypt_sensitive(user.phone_ciphertext)
    ip_fingerprint = _ip_fingerprint(ip_address)
    purpose = PhoneVerificationPurpose.PHONE_BINDING.value
    await _delete_expired_challenges(db, now)
    await _enforce_send_limits(
        db,
        phone_fingerprint=user.phone_fingerprint,
        ip_fingerprint=ip_fingerprint,
        purpose=purpose,
        now=now,
    )
    await _invalidate_previous_challenges(
        db,
        phone_fingerprint=user.phone_fingerprint,
        purpose=purpose,
        now=now,
    )
    challenge_id = UUID(secrets.token_hex(16))
    code = generate_sms_code()
    provider = get_sms_provider()
    challenge = PhoneVerificationChallenge(
        id=challenge_id,
        user_id=user.id,
        phone_fingerprint=user.phone_fingerprint,
        purpose=purpose,
        provider=provider.name,
        code_digest=_code_digest(challenge_id, code),
        request_ip_fingerprint=ip_fingerprint,
        max_attempts=settings.sms_max_attempts,
        expires_at=now + timedelta(seconds=settings.sms_code_expire_seconds),
        resend_available_at=now + timedelta(seconds=settings.sms_resend_seconds),
    )
    db.add(challenge)
    await db.flush()
    challenge.provider_reference = await provider.send_code(
        phone=phone,
        code=code,
        purpose=purpose,
        expires_in_seconds=settings.sms_code_expire_seconds,
    )
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="sms_code_requested",
        resource_type="phone_verification",
        resource_id=challenge.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    return PhoneChallengeOut(
        challenge_id=challenge.id,
        expires_in_seconds=settings.sms_code_expire_seconds,
        resend_after_seconds=settings.sms_resend_seconds,
    )


async def confirm_current_phone(
    db: AsyncSession,
    *,
    user: User,
    challenge_id: UUID,
    code: str,
) -> None:
    challenge = await _locked_challenge(db, challenge_id)
    if (
        challenge is None
        or challenge.user_id != user.id
        or challenge.purpose != PhoneVerificationPurpose.PHONE_BINDING.value
        or challenge.phone_fingerprint != user.phone_fingerprint
    ):
        raise AppError(422, "SMS_CHALLENGE_INVALID", "验证码请求无效，请重新获取")
    now = datetime.now(UTC)
    if challenge.consumed_at is not None:
        raise AppError(422, "SMS_CHALLENGE_INVALID", "验证码请求无效，请重新获取")
    if challenge.expires_at <= now:
        challenge.consumed_at = now
        await db.commit()
        raise AppError(422, "SMS_CODE_EXPIRED", "验证码已过期，请重新获取")
    if not hmac.compare_digest(_code_digest(challenge.id, code), challenge.code_digest):
        await _reject_code(db, challenge, code="SMS_CODE_INVALID")

    challenge.verified_at = now
    challenge.consumed_at = now
    user.phone_verified_at = now
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="phone_verified",
        resource_type="account",
        resource_id=user.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()


def _normalized_new_phone(value: str) -> str:
    try:
        return normalize_mainland_phone(value)
    except ValueError:
        raise AppError(422, "SMS_PHONE_INVALID", "请输入有效的中国大陆手机号") from None


async def _locked_user_with_credentials(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.scalar(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.id == user_id)
        .with_for_update()
    )


async def _ensure_phone_not_taken(db: AsyncSession, fingerprint: str, *, user_id: UUID) -> None:
    owner = await db.scalar(
        select(User.id).where(
            User.phone_fingerprint == fingerprint,
            User.id != user_id,
        )
    )
    if owner is not None:
        raise AppError(409, "PHONE_EXISTS", "该手机号已被注册")


async def request_phone_change_code(
    db: AsyncSession,
    *,
    user: User,
    new_phone: str,
    current_password: str,
    ip_address: str | None,
) -> PhoneChallengeOut:
    """换绑新手机号第一步：验当前密码 → 查重 → 给**新号码**发验证码。

    没有新增 `purpose` 值：`phone_verification_challenges` 上有
    `purpose IN ('registration','password_reset','phone_binding')` 的 CHECK 约束，
    加值就得写迁移。这里复用 `phone_binding`，靠 `phone_fingerprint` 区分两件事——
    指纹等于账户当前号的是「补验证」（`request_current_phone_code`），等于新号的
    才是换绑，所以下面这个挑战记的是新号码的指纹。
    """
    normalized_phone = _normalized_new_phone(new_phone)
    now = datetime.now(UTC)
    settings = get_settings()
    account = await _locked_user_with_credentials(db, user.id)
    if account is None or account.credentials is None:
        raise AppError(401, "UNAUTHORIZED", "当前未登录")
    if not verify_password(current_password, account.credentials.password_hash):
        await add_audit_log(
            db,
            actor_user_id=account.id,
            action="phone_change",
            resource_type="account",
            resource_id=account.id,
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code="ACCOUNT_PASSWORD_INVALID",
        )
        await db.commit()
        raise AppError(422, "ACCOUNT_PASSWORD_INVALID", "当前密码不正确")

    new_fingerprint = sensitive_fingerprint(normalized_phone)
    if new_fingerprint == account.phone_fingerprint:
        raise AppError(422, "PHONE_UNCHANGED", "新手机号与当前绑定的手机号相同")
    await _ensure_phone_not_taken(db, new_fingerprint, user_id=account.id)

    purpose = PhoneVerificationPurpose.PHONE_BINDING.value
    ip_fingerprint = _ip_fingerprint(ip_address)
    await _delete_expired_challenges(db, now)
    await _enforce_send_limits(
        db,
        phone_fingerprint=new_fingerprint,
        ip_fingerprint=ip_fingerprint,
        purpose=purpose,
        now=now,
    )
    await _invalidate_previous_challenges(
        db,
        phone_fingerprint=new_fingerprint,
        purpose=purpose,
        now=now,
    )
    challenge_id = UUID(secrets.token_hex(16))
    code = generate_sms_code()
    provider = get_sms_provider()
    challenge = PhoneVerificationChallenge(
        id=challenge_id,
        user_id=account.id,
        phone_fingerprint=new_fingerprint,
        purpose=purpose,
        provider=provider.name,
        code_digest=_code_digest(challenge_id, code),
        request_ip_fingerprint=ip_fingerprint,
        max_attempts=settings.sms_max_attempts,
        expires_at=now + timedelta(seconds=settings.sms_code_expire_seconds),
        resend_available_at=now + timedelta(seconds=settings.sms_resend_seconds),
    )
    db.add(challenge)
    await db.flush()
    challenge.provider_reference = await provider.send_code(
        phone=normalized_phone,
        code=code,
        purpose=purpose,
        expires_in_seconds=settings.sms_code_expire_seconds,
    )
    await add_audit_log(
        db,
        actor_user_id=account.id,
        action="sms_code_requested",
        resource_type="phone_verification",
        resource_id=challenge_id,
        outcome=AUDIT_OUTCOME_SUCCESS,
        reason_code="PHONE_CHANGE",
    )
    await db.commit()
    return PhoneChallengeOut(
        challenge_id=challenge_id,
        expires_in_seconds=settings.sms_code_expire_seconds,
        resend_after_seconds=settings.sms_resend_seconds,
    )


async def confirm_phone_change(
    db: AsyncSession,
    *,
    user: User,
    new_phone: str,
    challenge_id: UUID,
    code: str,
) -> User:
    """换绑第二步：校验新号码的验证码，然后把密文与指纹一起换掉。

    校验里必须带上 `new_fingerprint == user.phone_fingerprint` 的反向判断：否则
    用户可以把「当前号补验证」的挑战拿来当换绑用（两者共用 `phone_binding`）。
    """
    normalized_phone = _normalized_new_phone(new_phone)
    new_fingerprint = sensitive_fingerprint(normalized_phone)
    challenge = await _locked_challenge(db, challenge_id)
    if (
        challenge is None
        or challenge.user_id != user.id
        or challenge.purpose != PhoneVerificationPurpose.PHONE_BINDING.value
        or challenge.phone_fingerprint != new_fingerprint
        or new_fingerprint == user.phone_fingerprint
    ):
        raise AppError(422, "SMS_CHALLENGE_INVALID", "验证码请求无效，请重新获取")
    now = datetime.now(UTC)
    if challenge.consumed_at is not None:
        raise AppError(422, "SMS_CHALLENGE_INVALID", "验证码请求无效，请重新获取")
    if challenge.expires_at <= now:
        challenge.consumed_at = now
        await db.commit()
        raise AppError(422, "SMS_CODE_EXPIRED", "验证码已过期，请重新获取")
    if not hmac.compare_digest(_code_digest(challenge.id, code), challenge.code_digest):
        await _reject_code(db, challenge, code="SMS_CODE_INVALID")

    # 发码到确认之间号码可能已被别人注册，这里再查一次，并靠唯一约束兜底。
    await _ensure_phone_not_taken(db, new_fingerprint, user_id=user.id)
    user.phone_ciphertext = encrypt_sensitive(normalized_phone)
    user.phone_fingerprint = new_fingerprint
    user.phone_verified_at = now
    challenge.verified_at = now
    challenge.consumed_at = now
    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="phone_changed",
        resource_type="account",
        resource_id=user.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
        reason_code="PHONE_CHANGE",
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, "PHONE_EXISTS", "该手机号已被注册") from None
    await db.refresh(user)
    return user
