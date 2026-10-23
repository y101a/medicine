import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title_ciphertext: Mapped[str] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "client_request_id"),
        Index("ix_consultations_user_updated", "user_id", "updated_at", "id"),
    )


class ConsultationMemory(Base):
    """Encrypted, per-consultation summary of messages outside the recent window."""

    __tablename__ = "consultation_memories"

    consultation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consultations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    covered_through_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE")
    )
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16), default="user")
    content_ciphertext: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generation_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    answer_format: Mapped[str] = mapped_column(String(16), default="plain", server_default="plain")
    is_medical_content: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    triage_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("consultation_id", "client_request_id", name="uq_messages_request"),
        UniqueConstraint("consultation_id", "sequence", name="uq_messages_sequence"),
        Index(
            "uq_messages_source_card",
            "source_message_id",
            unique=True,
            postgresql_where=source_message_id.is_not(None),
        ),
    )
