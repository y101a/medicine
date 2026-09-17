from typing import Annotated

import jwt
from fastapi import Cookie, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User, UserStatus
from app.services.auth import ACCESS_COOKIE

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> User:
    if not access_token:
        raise AppError(401, "UNAUTHORIZED", "当前未登录")
    try:
        user_id = decode_access_token(access_token)
    except (jwt.InvalidTokenError, ValueError):
        raise AppError(401, "SESSION_EXPIRED", "登录状态已失效，请重新登录") from None

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise AppError(401, "UNAUTHORIZED", "当前未登录")
    if user.status != UserStatus.ACTIVE:
        raise AppError(403, "ACCOUNT_DISABLED", "该账户已被停用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
