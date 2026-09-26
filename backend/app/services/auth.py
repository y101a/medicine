from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    decrypt_sensitive,
    encrypt_sensitive,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    sensitive_fingerprint,
    verify_password,
)
from app.models import AuthSession, User, UserCredentials, UserStatus
from app.schemas.auth import AuthResult, AuthUser, LoginRequest, RegisterRequest
from app.services.validators import mask_id_card, mask_phone

ACCESS_COOKIE = "medical_access_token"
REFRESH_COOKIE = "medical_refresh_token"
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def to_auth_user(user: User) -> AuthUser:
    real_name = decrypt_sensitive(user.real_name_ciphertext)
    phone = decrypt_sensitive(user.phone_ciphertext)
    id_card = decrypt_sensitive(user.id_card_ciphertext)
    return AuthUser(
        id=user.id,
        username=user.username,
        real_name=real_name,
        gender=user.gender,
        role=user.role,
        phone_masked=mask_phone(phone),
        phone_verified=user.phone_verified_at is not None,
        id_card_masked=mask_id_card(id_card),
        registered_at=user.registered_at,
    )


def _client_metadata(request: Request) -> tuple[str | None, str | None]:
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    return user_agent[:512] if user_agent else None, ip_address[:64] if ip_address else None


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=f"{settings.api_v1_prefix}/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_v1_prefix}/auth")


async def register_user(payload: RegisterRequest, db: AsyncSession) -> AuthResult:
    username = payload.username.strip()
    normalized = normalize_username(username)
    phone_fingerprint = sensitive_fingerprint(payload.phone)
    id_card_fingerprint = sensitive_fingerprint(payload.id_card)

    from app.services.phone_verification import consume_registration_token

    if payload.phone_verification_token is None:
        raise AppError(
            422,
            "PHONE_VERIFICATION_REQUIRED",
            "请先完成手机号验证码验证",
        )
    challenge = await consume_registration_token(
        db,
        token=payload.phone_verification_token,
        phone_fingerprint=phone_fingerprint,
    )

    duplicate = await db.execute(
        select(User).where(
            (User.username_normalized == normalized)
            | (User.phone_fingerprint == phone_fingerprint)
            | (User.id_card_fingerprint == id_card_fingerprint)
        )
    )
    existing = duplicate.scalar_one_or_none()
    if existing:
        if existing.username_normalized == normalized:
            message, code = "该用户名已被使用", "USERNAME_EXISTS"
        elif existing.phone_fingerprint == phone_fingerprint:
            message, code = "该手机号已被注册", "PHONE_EXISTS"
        else:
            message, code = "该身份证信息已被注册", "ID_CARD_EXISTS"
        raise AppError(409, code, message)

    user = User(
        username=username,
        username_normalized=normalized,
        real_name_ciphertext=encrypt_sensitive(payload.real_name),
        phone_ciphertext=encrypt_sensitive(payload.phone),
        phone_fingerprint=phone_fingerprint,
        id_card_ciphertext=encrypt_sensitive(payload.id_card),
        id_card_fingerprint=id_card_fingerprint,
        gender=payload.gender,
        phone_verified_at=datetime.now(UTC),
    )
    user.credentials = UserCredentials(password_hash=hash_password(payload.password))
    db.add(user)
    try:
        await db.flush()
        challenge.user_id = user.id
        challenge.consumed_at = datetime.now(UTC)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, "REGISTRATION_CONFLICT", "该注册信息已被使用") from None
    await db.refresh(user)
    return AuthResult(user=to_auth_user(user))


async def login_user(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession,
) -> AuthResult:
    result = await db.execute(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.username_normalized == normalize_username(payload.username))
    )
    user = result.scalar_one_or_none()
    credentials = user.credentials if user else None

    if not user or not credentials:
        hash_password(payload.password)
        raise AppError(401, "INVALID_CREDENTIALS", "用户名或密码错误")

    now = datetime.now(UTC)
    if credentials.locked_until and credentials.locked_until > now:
        raise AppError(423, "ACCOUNT_LOCKED", "登录失败次数过多，请稍后再试")

    if not verify_password(payload.password, credentials.password_hash):
        credentials.failed_attempts += 1
        if credentials.failed_attempts >= MAX_FAILED_ATTEMPTS:
            credentials.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            credentials.failed_attempts = 0
        await db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "用户名或密码错误")

    if user.status != UserStatus.ACTIVE:
        raise AppError(403, "ACCOUNT_DISABLED", "该账户已被停用")

    credentials.failed_attempts = 0
    credentials.locked_until = None
    refresh_token = generate_refresh_token()
    settings = get_settings()
    user_agent, ip_address = _client_metadata(request)
    db.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await db.commit()
    _set_auth_cookies(
        response,
        create_access_token(user.id, user.auth_version),
        refresh_token,
    )
    return AuthResult(user=to_auth_user(user))


async def refresh_session(
    refresh_token: str | None,
    request: Request,
    response: Response,
    db: AsyncSession,
) -> AuthResult:
    if not refresh_token:
        raise AppError(401, "UNAUTHORIZED", "当前未登录")

    now = datetime.now(UTC)
    result = await db.execute(
        select(AuthSession)
        .options(selectinload(AuthSession.user))
        .where(AuthSession.refresh_token_hash == hash_refresh_token(refresh_token))
    )
    session = result.scalar_one_or_none()
    if not session or session.revoked_at or session.expires_at <= now:
        clear_auth_cookies(response)
        raise AppError(401, "SESSION_EXPIRED", "登录状态已失效，请重新登录")
    if session.user.status != UserStatus.ACTIVE:
        raise AppError(403, "ACCOUNT_DISABLED", "该账户已被停用")

    session.revoked_at = now
    new_refresh_token = generate_refresh_token()
    settings = get_settings()
    user_agent, ip_address = _client_metadata(request)
    db.add(
        AuthSession(
            user_id=session.user_id,
            refresh_token_hash=hash_refresh_token(new_refresh_token),
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await db.commit()
    _set_auth_cookies(
        response,
        create_access_token(session.user_id, session.user.auth_version),
        new_refresh_token,
    )
    return AuthResult(user=to_auth_user(session.user))


async def logout_session(refresh_token: str | None, response: Response, db: AsyncSession) -> None:
    if refresh_token:
        result = await db.execute(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == hash_refresh_token(refresh_token)
            )
        )
        session = result.scalar_one_or_none()
        if session and not session.revoked_at:
            session.revoked_at = datetime.now(UTC)
            await db.commit()
    clear_auth_cookies(response)
