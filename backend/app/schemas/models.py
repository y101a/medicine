from pydantic import BaseModel, Field


class ModelOut(BaseModel):
    id: str
    name: str
    provider: str
    provider_name: str = Field(serialization_alias="providerName")
    description: str
    is_default: bool = Field(serialization_alias="isDefault")


class ModelList(BaseModel):
    items: list[ModelOut]
