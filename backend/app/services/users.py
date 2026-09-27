from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.security import encrypt_sensitive, verify_password
from app.models import User
from app.schemas.auth import AuthUser
from app.schemas.users import UpdateProfileRequest
from app.services.audit_logs import (
    AUDIT_OUTCOME_REJECTED,
    AUDIT_OUTCOME_SUCCESS,
    add_audit_log,
)
from app.services.auth import normalize_username, to_auth_user


async def update_profile(user: User, payload: UpdateProfileRequest, db: AsyncSession) -> AuthUser:
    # Only assign editable fields to the user identified by the authentication dependency.
    if payload.username is not None:
        await _change_username(
            db,
            user,
            username=payload.username,
            current_password=payload.current_password,
        )
    if payload.real_name is not None:
        user.real_name_ciphertext = encrypt_sensitive(payload.real_name)
    if payload.gender is not None:
        user.gender = payload.gender
    await db.commit()
    await db.refresh(user)
    return to_auth_user(user)


async def _change_username(
    db: AsyncSession,
    user: User,
    *,
    username: str,
    current_password: str | None,
) -> None:
    """改登录名：先验当前密码，再查重（与注册同一套唯一键 `username_normalized`）。

    重新加行锁读取是必须的：登录名与规范化登录名必须一起改，冲突检查也不能只看
    依赖注入里那个可能已过期的对象。锁持有到 `update_profile` 结尾的那次 commit。
    """
    account = await db.scalar(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.id == user.id)
        .with_for_update()
    )
    if account is None or account.credentials is None:
        raise AppError(401, "UNAUTHORIZED", "当前未登录")
    if not verify_password(current_password or "", account.credentials.password_hash):
        await add_audit_log(
            db,
            actor_user_id=account.id,
            action="update",
            resource_type="username",
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code="ACCOUNT_PASSWORD_INVALID",
        )
        await db.commit()
        raise AppError(422, "ACCOUNT_PASSWORD_INVALID", "当前密码不正确")

    normalized = normalize_username(username)
    taken_by_other = await db.scalar(
        select(User.id).where(
            User.username_normalized == normalized,
            User.id != account.id,
        )
    )
    if taken_by_other is not None:
        raise AppError(409, "USERNAME_EXISTS", "该用户名已被使用")

    account.username = username
    account.username_normalized = normalized
    await add_audit_log(
        db,
        actor_user_id=account.id,
        action="update",
        resource_type="username",
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    try:
        await db.flush()
    except IntegrityError:
        # 两个并发改名撞到同一个规范化登录名时靠唯一约束兜底。
        await db.rollback()
        raise AppError(409, "USERNAME_EXISTS", "该用户名已被使用") from None
