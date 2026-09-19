from typing import Literal

from pydantic import BaseModel, Field


class ModelOut(BaseModel):
    id: str
    name: str
    provider: str
    provider_name: str = Field(serialization_alias="providerName")
    description: str
    is_default: bool = Field(serialization_alias="isDefault")
    key_source: Literal["server", "user"] = Field(serialization_alias="keySource")


class ModelList(BaseModel):
    items: list[ModelOut]
