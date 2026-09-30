from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DocumentFormat = Literal["docx", "pptx"]
DocumentGenerationStatus = Literal[
    "queued", "generating", "rendering", "completed", "failed", "cancelled", "expired"
]


class CreateDocumentGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: UUID = Field(alias="clientRequestId")
    source_message_id: UUID = Field(alias="sourceMessageId")
    notice_accepted: bool = Field(default=False, alias="noticeAccepted")
    notice_version: str = Field(default="", alias="noticeVersion", max_length=64)


class GeneratedDocumentFileOut(BaseModel):
    id: UUID
    format: DocumentFormat
    mime_type: str = Field(serialization_alias="mimeType")
    byte_size: int = Field(serialization_alias="byteSize", gt=0)
    page_count: int | None = Field(default=None, serialization_alias="pageCount", gt=0)
    available: bool


class DocumentGenerationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_message_id: UUID = Field(serialization_alias="sourceMessageId")
    status: DocumentGenerationStatus
    formats: list[DocumentFormat]
    title: str | None = None
    model: str
    template_mode: Literal["default", "builtin", "uploaded"] = Field(
        serialization_alias="templateMode"
    )
    files: list[GeneratedDocumentFileOut] = Field(default_factory=list)
    source_count: int = Field(default=0, serialization_alias="sourceCount", ge=0)
    error_code: str | None = Field(default=None, serialization_alias="errorCode")
    expires_at: datetime | None = Field(default=None, serialization_alias="expiresAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class DocumentGenerationList(BaseModel):
    items: list[DocumentGenerationOut]
