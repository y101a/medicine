from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelCredentialWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(alias="apiKey", min_length=8, max_length=512)

    @field_validator("api_key", mode="before")
    @classmethod
    def trim_api_key(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ModelCredentialOut(BaseModel):
    provider: str
    masked_key: str = Field(serialization_alias="maskedKey")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    last_verified_at: datetime = Field(serialization_alias="lastVerifiedAt")


class ModelCredentialList(BaseModel):
    items: list[ModelCredentialOut]
