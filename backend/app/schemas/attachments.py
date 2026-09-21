from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AttachmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    display_name: str = Field(serialization_alias="displayName", min_length=1, max_length=120)
    kind: Literal["pdf", "docx", "pptx", "txt", "md"]
    byte_size: int = Field(serialization_alias="byteSize", ge=1, le=30 * 1024 * 1024)
    page_count: int | None = Field(default=None, serialization_alias="pageCount", ge=1, le=100)
    char_count: int = Field(serialization_alias="charCount", ge=1, le=500_000)
    preview: str = Field(max_length=201)
    status: Literal["ready"] = "ready"
    created_at: datetime = Field(serialization_alias="createdAt")


class AttachmentList(BaseModel):
    items: list[AttachmentOut]


class MessageAttachmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None
    display_name: str = Field(serialization_alias="displayName", min_length=1, max_length=120)
    kind: Literal["pdf", "docx", "pptx", "txt", "md"] | None = None
    status: Literal["ready", "deleted"]
