from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.models import ModelList, ModelOut
from app.services.model_credentials import available_models_for_user

router = APIRouter(prefix="/models", tags=["模型"])


@router.get("", response_model=ModelList)
async def get_available_models(user: CurrentUser, db: DbSession):
    models = await available_models_for_user(db, user.id)
    return ModelList(
        items=[
            ModelOut(
                id=model.id,
                name=model.name,
                provider=model.provider,
                provider_name=model.provider_name,
                description=model.description,
                is_default=index == 0,
                key_source=model.key_source,
            )
            for index, model in enumerate(models)
        ]
    )
