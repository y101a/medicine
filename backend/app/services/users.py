from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_sensitive
from app.models import User
from app.schemas.auth import AuthUser
from app.schemas.users import UpdateProfileRequest
from app.services.auth import to_auth_user


async def update_profile(user: User, payload: UpdateProfileRequest, db: AsyncSession) -> AuthUser:
    # Only assign editable fields to the user identified by the authentication dependency.
    if payload.real_name is not None:
        user.real_name_ciphertext = encrypt_sensitive(payload.real_name)
    if payload.gender is not None:
        user.gender = payload.gender
    await db.commit()
    await db.refresh(user)
    return to_auth_user(user)
