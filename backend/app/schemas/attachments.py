from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ImageCategory = Literal[
    "report", "medical_imaging", "body_photo", "medication_leaflet", "unrelated"
]
AttachmentKindValue = Literal["pdf", "docx", "pptx", "txt", "md", "image"]


class AttachmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    display_name: str = Field(serialization_alias="displayName", min_length=1, max_length=120)
    kind: AttachmentKindValue
    byte_size: int = Field(serialization_alias="byteSize", ge=1, le=30 * 1024 * 1024)
    page_count: int | None = Field(default=None, serialization_alias="pageCount", ge=1, le=100)
    char_count: int = Field(serialization_alias="charCount", ge=1, le=500_000)
    preview: str = Field(max_length=201)
    status: Literal["ready"] = "ready"
    created_at: datetime = Field(serialization_alias="createdAt")
    image_category: ImageCategory | None = Field(default=None, serialization_alias="imageCategory")
    mime_type: Literal["image/webp"] | None = Field(default=None, serialization_alias="mimeType")
    image_width: int | None = Field(default=None, serialization_alias="width")
    image_height: int | None = Field(default=None, serialization_alias="height")
    image_available: bool | None = Field(default=None, serialization_alias="imageAvailable")
    image_expires_at: datetime | None = Field(default=None, serialization_alias="imageExpiresAt")


class AttachmentList(BaseModel):
    items: list[AttachmentOut]


class MessageAttachmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None
    display_name: str = Field(serialization_alias="displayName", min_length=1, max_length=120)
    kind: AttachmentKindValue | None = None
    status: Literal["ready", "deleted"]
    image_category: ImageCategory | None = Field(default=None, serialization_alias="imageCategory")
    mime_type: Literal["image/webp"] | None = Field(default=None, serialization_alias="mimeType")
    image_available: bool | None = Field(default=None, serialization_alias="imageAvailable")
    image_expires_at: datetime | None = Field(default=None, serialization_alias="imageExpiresAt")
