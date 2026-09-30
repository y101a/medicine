from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ImageGenerationStyle = Literal["medical_illustration", "flat_illustration", "friendly_cartoon"]
ImageAspectRatio = Literal["1:1", "4:3", "3:4", "16:9"]
ImageGenerationStatus = Literal[
    "submitted", "running", "reviewing", "completed", "failed", "cancelled", "expired"
]


class CreateImageGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID = Field(alias="clientRequestId")
    source_message_id: UUID = Field(alias="sourceMessageId")
    prompt: str = Field(min_length=1, max_length=500)
    style: ImageGenerationStyle = "medical_illustration"
    aspect_ratio: ImageAspectRatio = Field(default="4:3", alias="aspectRatio")
    notice_accepted: bool = Field(default=False, alias="noticeAccepted")
    notice_version: str = Field(default="", alias="noticeVersion", max_length=64)

    @field_validator("prompt", mode="before")
    @classmethod
    def trim_prompt(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ImageGenerationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    content_id: UUID = Field(serialization_alias="contentId")
    source_message_id: UUID = Field(serialization_alias="sourceMessageId")
    status: ImageGenerationStatus
    style: ImageGenerationStyle
    aspect_ratio: ImageAspectRatio = Field(serialization_alias="aspectRatio")
    model: str
    image_available: bool = Field(serialization_alias="imageAvailable")
    image_expires_at: datetime | None = Field(default=None, serialization_alias="imageExpiresAt")
    error_code: str | None = Field(default=None, serialization_alias="errorCode")
    review_summary: str | None = Field(default=None, serialization_alias="reviewSummary")
    regeneration_count: int = Field(serialization_alias="regenerationCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ImageGenerationList(BaseModel):
    items: list[ImageGenerationOut]
