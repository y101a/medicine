import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import enum_values


class HealthRecordCategory(StrEnum):
    """Whitelisted buckets; keeps stored facts structured and displayable."""

    GENERAL_STATUS = "general_status"
    SYMPTOM = "symptom"
    CONDITION = "condition"
    MEDICATION = "medication"
    ALLERGY = "allergy"
    LIFESTYLE = "lifestyle"
    MEASUREMENT = "measurement"
    CARE_SEEKING = "care_seeking"
    OTHER = "other"


class HealthRecordSource(StrEnum):
    ONBOARDING = "onboarding"
    CONVERSATION = "conversation"
    USER = "user"


# Display labels, also handed to the extraction prompt as the allowed buckets.
CATEGORY_LABELS: dict[HealthRecordCategory, str] = {
    HealthRecordCategory.GENERAL_STATUS: "近期身体状态",
    HealthRecordCategory.SYMPTOM: "近期症状",
    HealthRecordCategory.CONDITION: "长期健康情况（用户自述）",
    HealthRecordCategory.MEDICATION: "正在使用的药物",
    HealthRecordCategory.ALLERGY: "过敏史",
    HealthRecordCategory.LIFESTYLE: "生活方式",
    HealthRecordCategory.MEASUREMENT: "自测指标",
    HealthRecordCategory.CARE_SEEKING: "就医情况",
    HealthRecordCategory.OTHER: "其他",
}

# Onboarding choices shown once after login; stored as a self-stated status fact.
ONBOARDING_STATUS_LABELS: dict[str, str] = {
    "good": "最近感觉身体状态不错",
    "fair": "最近身体状态一般",
    "poor": "最近身体状态不太好",
    "unsure": "暂时说不清自己的身体状态",
}


class HealthRecord(Base):
    """One user-stated health fact.

    Only facts the user stated themselves are stored; model inferences are never
    persisted here. The text is encrypted with the project field key.
    """

    __tablename__ = "health_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[HealthRecordCategory] = mapped_column(
        Enum(
            HealthRecordCategory,
            name="health_record_category_enum",
            values_callable=enum_values,
        )
    )
    content_ciphertext: Mapped[str] = mapped_column(Text)
    # Non-reversible digest used only to avoid storing the same fact twice.
    content_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[HealthRecordSource] = mapped_column(
        Enum(
            HealthRecordSource,
            name="health_record_source_enum",
            values_callable=enum_values,
        ),
        default=HealthRecordSource.USER,
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "category",
            "content_hash",
            name="uq_health_records_user_category_hash",
        ),
        Index("ix_health_records_user_recorded", "user_id", "recorded_at"),
    )


class HealthRecordSettings(Base):
    """Per-user collection switch and first-notice bookkeeping."""

    __tablename__ = "health_record_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Defaults to collecting, per the confirmed product decision; the user can
    # turn it off at any time and the first notice offers the same option.
    collection_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    notice_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Idempotency guard so one consultation exchange is extracted only once.
    last_extracted_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )