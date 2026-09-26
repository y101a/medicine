from fastapi import APIRouter, Request, Response, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.phone_verification import (
    PhoneChallengeOut,
    PhoneCodeVerifyRequest,
)
from app.services.phone_verification import (
    confirm_current_phone,
    request_current_phone_code,
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
