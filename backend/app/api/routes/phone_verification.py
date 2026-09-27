from fastapi import APIRouter, Request, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.auth import AuthUser
from app.schemas.phone_verification import (
    PhoneChallengeOut,
    PhoneChangeCodeRequest,
    PhoneChangeRequest,
    PhoneCodeVerifyRequest,
)
from app.services.auth import to_auth_user
from app.services.phone_verification import (
    confirm_current_phone,
    confirm_phone_change,
    request_current_phone_code,
    request_phone_change_code,
)

router = APIRouter(prefix="/users/me/phone-verification", tags=["用户"])


@router.post(
    "/code",
    response_model=PhoneChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_current_phone_verification_code(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> PhoneChallengeOut:
    return await request_current_phone_code(
        db,
        user=current_user,
        ip_address=request.client.host if request.client else None,
    )


@router.post("/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_current_phone_verification(
    payload: PhoneCodeVerifyRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    await confirm_current_phone(
        db,
        user=current_user,
        challenge_id=payload.challenge_id,
        code=payload.code,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/change-code",
    response_model=PhoneChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="给新手机号发送换绑验证码（需当前密码）",
)
async def request_phone_change_verification_code(
    payload: PhoneChangeCodeRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> PhoneChallengeOut:
    return await request_phone_change_code(
        db,
        user=current_user,
        new_phone=payload.phone,
        current_password=payload.current_password,
        ip_address=request.client.host if request.client else None,
    )


@router.post("/change", response_model=AuthUser, summary="用验证码把绑定手机号换成新号码")
async def confirm_phone_change_verification(
    payload: PhoneChangeRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> AuthUser:
    user = await confirm_phone_change(
        db,
        user=current_user,
        new_phone=payload.phone,
        challenge_id=payload.challenge_id,
        code=payload.code,
    )
    return to_auth_user(user)
