from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.health_record import HealthRecordCategory, HealthRecordSource

MAX_RECORD_CHARS = 500


class HealthRecordOut(BaseModel):
    id: UUID
    category: HealthRecordCategory
    category_label: str = Field(serialization_alias="categoryLabel")
    content: str
    source: HealthRecordSource
    recorded_at: datetime = Field(serialization_alias="recordedAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class HealthRecordList(BaseModel):
    items: list[HealthRecordOut]


class HealthRecordSettingsOut(BaseModel):
    collection_enabled: bool = Field(serialization_alias="collectionEnabled")
    notice_seen: bool = Field(serialization_alias="noticeSeen")
    record_count: int = Field(serialization_alias="recordCount")


class HealthRecordSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_enabled: bool | None = Field(default=None, alias="collectionEnabled")
    notice_seen: bool | None = Field(default=None, alias="noticeSeen")

    @model_validator(mode="after")
    def check_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("请至少提供一个需要修改的字段")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("字段不能设为 null")
        return self


class HealthRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: HealthRecordCategory
    content: str = Field(min_length=1, max_length=MAX_RECORD_CHARS)

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class HealthRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: HealthRecordCategory | None = None
    content: str | None = Field(default=None, min_length=1, max_length=MAX_RECORD_CHARS)

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def check_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("请至少提供一个需要修改的字段")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("记录内容不能设为 null")
        return self


class HealthRecordOnboarding(BaseModel):
    """First-login status choice; the user may also skip the whole dialog."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["good", "fair", "poor", "unsure"]
    note: str | None = Field(default=None, max_length=200)

    @field_validator("note", mode="before")
    @classmethod
    def trim_note(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class HealthRecordExtractRequest(BaseModel):
    """Ask the backend to update records from one completed user message."""

    model_config = ConfigDict(extra="forbid")

    consultation_id: UUID = Field(alias="consultationId")
    message_id: UUID = Field(alias="messageId")
