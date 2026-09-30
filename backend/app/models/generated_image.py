"""Persistent AI-generated image tasks and encrypted results."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False
    )
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    prompt_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str] = mapped_column(String(32), nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="submitted")
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_task_id_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    review_summary_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    regeneration_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "style IN ('medical_illustration', 'flat_illustration', 'friendly_cartoon')",
            name="style_supported",
        ),
        CheckConstraint(
            "aspect_ratio IN ('1:1', '4:3', '3:4', '16:9')", name="aspect_ratio_supported"
        ),
        CheckConstraint(
            "status IN ('submitted', 'running', 'reviewing', 'completed', 'failed', "
            "'cancelled', 'expired')",
            name="status_supported",
        ),
        CheckConstraint("poll_count >= 0", name="poll_count_nonnegative"),
        CheckConstraint("review_attempt_count >= 0", name="review_attempt_count_nonnegative"),
        CheckConstraint("regeneration_count BETWEEN 0 AND 1", name="regeneration_count_supported"),
        CheckConstraint(
            "(status = 'completed' AND storage_key IS NOT NULL "
            "AND image_key_ciphertext IS NOT NULL "
            "AND mime_type = 'image/webp' AND width IS NOT NULL AND height IS NOT NULL "
            "AND byte_size IS NOT NULL AND image_expires_at IS NOT NULL "
            "AND completed_at IS NOT NULL "
            "AND image_deleted_at IS NULL AND provider_task_id_ciphertext IS NULL) OR "
            "(status = 'reviewing' AND storage_key IS NOT NULL "
            "AND image_key_ciphertext IS NOT NULL AND mime_type = 'image/webp' "
            "AND width IS NOT NULL AND height IS NOT NULL AND byte_size IS NOT NULL "
            "AND image_expires_at IS NULL AND completed_at IS NULL "
            "AND image_deleted_at IS NULL AND provider_task_id_ciphertext IS NULL) OR "
            "(status NOT IN ('completed', 'reviewing') AND storage_key IS NULL "
            "AND image_key_ciphertext IS NULL "
            "AND mime_type IS NULL AND width IS NULL AND height IS NULL AND byte_size IS NULL)",
            name="storage_state_supported",
        ),
        Index(
            "uq_generated_images_user_client_request", "user_id", "client_request_id", unique=True
        ),
        Index(
            "uq_generated_images_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('submitted', 'running', 'reviewing')"),
        ),
        Index("ix_generated_images_user_created", "user_id", "created_at"),
        Index("ix_generated_images_status_poll", "status", "next_poll_at"),
        Index(
            "ix_generated_images_consultation_source_created",
            "consultation_id",
            "source_message_id",
            "created_at",
        ),
        Index(
            "ix_generated_images_expiry",
            "image_expires_at",
            postgresql_where=text("status = 'completed'"),
        ),
    )


class GeneratedImageDeliveryLog(Base):
    """Six-month minimum trace log for watermark-free file delivery."""

    __tablename__ = "generated_image_delivery_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_consultation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_generated_image_delivery_content_recipient",
            "content_id",
            "recipient_fingerprint",
            unique=True,
        ),
        Index("ix_generated_image_delivery_retain_until", "retain_until"),
    )
