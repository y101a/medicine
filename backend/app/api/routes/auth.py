from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.api.dependencies import DbSession
from app.core.errors import AppError
from app.schemas.auth import AuthResult, LoginRequest, RegisterRequest
from app.schemas.phone_verification import (
    PasswordResetRequest,
    PhoneChallengeOut,
    PhoneCodeRequest,
    PhoneCodeVerifyRequest,
    PhoneVerificationTokenOut,
    normalize_mainland_phone,
)
from app.services.auth import (
    REFRESH_COOKIE,
    login_user,
    logout_session,
    refresh_session,
    register_user,
)
from app.services.phone_verification import (
    request_public_code,
    reset_password,
    verify_public_code,
)

router = APIRouter(prefix="/auth", tags=["认证"])


def _validated_phone(phone: str) -> str:
    try:
        return normalize_mainland_phone(phone)
    except ValueError:
        raise AppError(422, "SMS_PHONE_INVALID", "请输入有效的中国大陆手机号") from None


@router.post(
    "/phone-verifications/code",
    response_model=PhoneChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_phone_verification_code(
    payload: PhoneCodeRequest,
    request: Request,
    db: DbSession,
) -> PhoneChallengeOut:
    from app.models import PhoneVerificationPurpose

    return await request_public_code(
        db,
        phone=_validated_phone(payload.phone),
        purpose=PhoneVerificationPurpose(payload.purpose),
        ip_address=request.client.host if request.client else None,
    )


@router.post(
    "/phone-verifications/verify",
    response_model=PhoneVerificationTokenOut,
)
async def verify_phone_verification_code(
    payload: PhoneCodeVerifyRequest,
    db: DbSession,
) -> PhoneVerificationTokenOut:
    return await verify_public_code(
        db,
        challenge_id=payload.challenge_id,
        code=payload.code,
    )


@router.post("/register", response_model=AuthResult, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> AuthResult:
    return await register_user(payload, db)


@router.post("/login", response_model=AuthResult)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> AuthResult:
    return await login_user(payload, request, response, db)


@router.post("/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def password_reset(payload: PasswordResetRequest, db: DbSession) -> Response:
    await reset_password(
        db,
        phone=_validated_phone(payload.phone),
        verification_token=payload.verification_token,
        new_password=payload.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/refresh", response_model=AuthResult)
async def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> AuthResult:
    return await refresh_session(refresh_token, request, response, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> None:
    await logout_session(refresh_token, response, db)
