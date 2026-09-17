from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.api.dependencies import DbSession
from app.schemas.auth import AuthResult, LoginRequest, RegisterRequest
from app.services.auth import (
    REFRESH_COOKIE,
    login_user,
    logout_session,
    refresh_session,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=AuthResult, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> AuthResult:
    return await register_user(payload, db)


@router.post("/login", response_model=AuthResult)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> AuthResult:
    return await login_user(payload, request, response, db)


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
