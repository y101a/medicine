from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FollowUpOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=24)


class FollowUpQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=2, max_length=60)
    type: Literal["single_choice", "multiple_choice", "scale", "text"]
    required: bool = True
    options: list[FollowUpOption] = Field(default_factory=list, max_length=8)
    min_value: int | None = Field(default=None, alias="min", ge=0, le=10)
    max_value: int | None = Field(default=None, alias="max", ge=1, le=10)

    @model_validator(mode="after")
    def validate_control(self):
        if self.type in {"single_choice", "multiple_choice"}:
            if len(self.options) < 2:
                raise ValueError("选择题至少需要两个选项")
            values = [option.value for option in self.options]
            if len(values) != len(set(values)):
                raise ValueError("选项值不能重复")
        elif self.options:
            raise ValueError("非选择题不能包含选项")
        if self.type == "scale":
            if self.min_value is None or self.max_value is None:
                raise ValueError("程度题必须提供范围")
            if self.min_value >= self.max_value:
                raise ValueError("程度题范围无效")
        elif self.min_value is not None or self.max_value is not None:
            raise ValueError("只有程度题可以包含范围")
        return self


class FollowUpCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intro: str = Field(min_length=2, max_length=120)
    questions: list[FollowUpQuestion] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def unique_question_ids(self):
        ids = [question.id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("问题编号不能重复")
        return self


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["emergency"]
    rule_version: str = Field(
        default="2026-09-10.2", serialization_alias="ruleVersion"
    )
    assessment_method: Literal["deterministic_rules"] = Field(
        default="deterministic_rules", serialization_alias="assessmentMethod"
    )
    title: str
    summary: str
    reasons: list[str]
    actions: list[str]
    rule_ids: list[str] = Field(serialization_alias="ruleIds")
    assessed_at: datetime = Field(serialization_alias="assessedAt")


class MessageCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_number: int | None = Field(
        default=None, serialization_alias="referenceNumber", ge=1
    )
    source_key: str = Field(serialization_alias="sourceKey", min_length=1, max_length=128)
    organization: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=500)
    canonical_url: str = Field(serialization_alias="canonicalUrl", min_length=1, max_length=2000)
    section_title: str | None = Field(
        default=None,
        serialization_alias="sectionTitle",
        max_length=500,
    )
    similarity: float = Field(ge=-1, le=1)
    trust_level: Literal["approved", "prototype"] = Field(
        serialization_alias="trustLevel"
    )


class CreateConsultation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID = Field(alias="clientRequestId")


class CreateMessage(CreateConsultation):
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CreateGeneration(CreateConsultation):
    model_id: str = Field(alias="modelId", min_length=1, max_length=128)
    answer_format: Literal["plain", "card"] = Field(default="plain", alias="answerFormat")
    source_message_id: UUID | None = Field(default=None, alias="sourceMessageId")


class ConsultationOut(BaseModel):
    id: UUID
    title: str
    message_count: int = Field(serialization_alias="messageCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ConsultationPage(BaseModel):
    items: list[ConsultationOut]
    has_more: bool = Field(serialization_alias="hasMore")


class MessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    sequence: int
    provider: str | None = None
    model_id: str | None = Field(default=None, serialization_alias="modelId")
    model_name: str | None = Field(default=None, serialization_alias="modelName")
    generation_status: str | None = Field(default=None, serialization_alias="generationStatus")
    answer_format: Literal["plain", "card"] = Field(
        default="plain",
        serialization_alias="answerFormat",
    )
    medical_content: bool = Field(default=False, serialization_alias="medicalContent")
    source_message_id: UUID | None = Field(default=None, serialization_alias="sourceMessageId")
    follow_up: FollowUpCard | None = Field(default=None, serialization_alias="followUp")
    triage: TriageResult | None = None
    citations: list[MessageCitation] = Field(default_factory=list)
    created_at: datetime = Field(serialization_alias="createdAt")


class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool = Field(serialization_alias="hasMore")
