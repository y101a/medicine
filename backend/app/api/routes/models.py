from fastapi import APIRouter

from app.ai.registry import available_models
from app.api.dependencies import CurrentUser
from app.schemas.models import ModelList, ModelOut

router = APIRouter(prefix="/models", tags=["模型"])


@router.get("", response_model=ModelList)
async def get_available_models(user: CurrentUser):
    models = available_models()
    return ModelList(
        items=[
            ModelOut(
                id=model.id,
                name=model.name,
                provider=model.provider,
                provider_name=model.provider_name,
                description=model.description,
                is_default=index == 0,
            )
            for index, model in enumerate(models)
        ]
    )
