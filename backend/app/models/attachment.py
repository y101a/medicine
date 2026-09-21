import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AttachmentKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"
    MARKDOWN = "md"
    IMAGE = "image"


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False
    )
    display_name_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    image_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_storage_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    image_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    analysis_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analysis_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('pdf', 'docx', 'pptx', 'txt', 'md', 'image')",
            name="kind_supported",
        ),
        CheckConstraint(
            "byte_size BETWEEN 1 AND 31457280", name="byte_size_supported"
        ),
        CheckConstraint(
            "page_count IS NULL OR page_count BETWEEN 1 AND 100",
            name="page_count_supported",
        ),
        CheckConstraint("char_count BETWEEN 1 AND 500000", name="char_count_supported"),
        CheckConstraint("status = 'ready'", name="status_supported"),
        CheckConstraint(
            "image_category IS NULL OR image_category IN "
            "('report', 'medical_imaging', 'body_photo')",
            name="image_category_supported",
        ),
        CheckConstraint(
            "(image_width IS NULL AND image_height IS NULL) OR "
            "(image_width BETWEEN 32 AND 2400 AND image_height BETWEEN 32 AND 2400)",
            name="image_dimensions_supported",
        ),
        CheckConstraint(
            "kind <> 'image' OR (image_category IS NOT NULL AND mime_type = 'image/webp' "
            "AND image_width IS NOT NULL AND image_height IS NOT NULL "
            "AND image_expires_at IS NOT NULL AND analysis_model IS NOT NULL "
            "AND analysis_version IS NOT NULL)",
            name="image_metadata_required",
        ),
        CheckConstraint(
            "kind <> 'image' OR "
            "((image_storage_key IS NOT NULL AND image_key_ciphertext IS NOT NULL "
            "AND image_deleted_at IS NULL) OR "
            "(image_storage_key IS NULL AND image_key_ciphertext IS NULL "
            "AND image_deleted_at IS NOT NULL))",
            name="image_storage_state_supported",
        ),
        Index(
            "ix_attachments_image_expiry",
            "image_expires_at",
            postgresql_where=text("kind = 'image' AND image_deleted_at IS NULL"),
        ),
        Index(
            "ix_attachments_user_consultation_created",
            "user_id",
            "consultation_id",
            "created_at",
            "id",
        ),
    )


class AttachmentChunk(Base):
    __tablename__ = "attachment_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[str] = mapped_column(String(64), nullable=False)
    content_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("attachment_id", "position", name="uq_attachment_chunks_position"),
        Index("ix_attachment_chunks_attachment", "attachment_id", "position"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint("char_count BETWEEN 1 AND 4000", name="char_count_supported"),
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "position", name="uq_message_attachments_position"),
        UniqueConstraint("message_id", "attachment_id", name="uq_message_attachments_attachment"),
        CheckConstraint("position BETWEEN 0 AND 4", name="position_supported"),
        Index("ix_message_attachments_message", "message_id", "position"),
        Index("ix_message_attachments_attachment", "attachment_id"),
    )
