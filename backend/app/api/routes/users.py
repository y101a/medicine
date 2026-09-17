from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import CurrentUser, DbSession
from app.core.errors import AppError
from app.schemas.auth import AuthUser
from app.schemas.users import UpdateProfileRequest
from app.services.auth import to_auth_user
from app.services.avatars import avatar_path, save_avatar
from app.services.users import update_profile

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/me", response_model=AuthUser)
async def get_me(current_user: CurrentUser) -> AuthUser:
    return to_auth_user(current_user)


@router.patch("/me", response_model=AuthUser)
async def patch_me(
    payload: UpdateProfileRequest, current_user: CurrentUser, db: DbSession
) -> AuthUser:
    return await update_profile(current_user, payload, db)


@router.get("/me/avatar", response_class=FileResponse)
async def get_my_avatar(current_user: CurrentUser) -> FileResponse:
    path = avatar_path(current_user.id)
    if not path.is_file():
        raise AppError(404, "AVATAR_NOT_FOUND", "尚未设置头像")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.put("/me/avatar")
async def put_my_avatar(
    current_user: CurrentUser,
    avatar: Annotated[UploadFile, File()],
) -> dict[str, str]:
    await save_avatar(current_user.id, avatar)
    return {"avatarUrl": "/api/v1/users/me/avatar"}
