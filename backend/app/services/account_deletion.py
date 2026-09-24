from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.core.security import verify_password
from app.models import User
from app.services import attachments as attachment_service
from app.services import image_generations as image_generation_service
from app.services.audit_logs import (
    AUDIT_OUTCOME_REJECTED,
    AUDIT_OUTCOME_SUCCESS,
    add_audit_log,
)
from app.services.avatars import delete_avatar
from app.services.image_deletion import (
    enqueue_image_deletions,
    process_image_deletion_jobs_best_effort,
)


async def delete_account(
    db: AsyncSession,
    user_id: UUID,
    current_password: str,
) -> None:
    user = await db.scalar(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.id == user_id)
        .with_for_update()
    )
    if user is None or user.credentials is None:
        raise AppError(401, "UNAUTHORIZED", "当前未登录")
    if not verify_password(current_password, user.credentials.password_hash):
        await add_audit_log(
            db,
            actor_user_id=user_id,
            action="delete",
            resource_type="account",
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code="ACCOUNT_PASSWORD_INVALID",
        )
        await db.commit()
        raise AppError(422, "ACCOUNT_PASSWORD_INVALID", "当前密码不正确")

    # Capture encrypted blob keys before the database cascade removes attachment rows.
    image_keys = await attachment_service.image_storage_keys_for_user(db, user_id)
    image_keys.extend(await image_generation_service.storage_keys_for_user(db, user_id))
    await enqueue_image_deletions(
        db,
        image_keys,
        "ACCOUNT_DELETED",
    )
    # Filesystem data cannot participate in the database transaction. Remove the
    # avatar first so a successful account deletion never leaves that personal file behind.
    delete_avatar(user_id)
    await add_audit_log(
        db,
        actor_user_id=user_id,
        action="delete",
        resource_type="account",
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.delete(user)
    await db.commit()
    await process_image_deletion_jobs_best_effort(
        db,
        storage_keys=image_keys,
    )
