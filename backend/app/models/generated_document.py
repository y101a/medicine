"""Persistent AI-generated educational document tasks and encrypted files."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

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
    requested_formats: Mapped[list[str]] = mapped_column(ARRAY(String(8)), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    workflow_stage: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    multi_agent_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    template_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="default", server_default="default"
    )
    title_ciphertext: Mapped[str | None] = mapped_column(Text)
    content_plan_ciphertext: Mapped[str | None] = mapped_column(Text)
    source_snapshot_ciphertext: Mapped[str | None] = mapped_column(Text)
    source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'generating', 'rendering', 'completed', 'failed', "
            "'cancelled', 'expired')",
            name="status_supported",
        ),
        CheckConstraint(
            "cardinality(requested_formats) BETWEEN 1 AND 2 "
            "AND requested_formats <@ ARRAY['docx', 'pptx']::varchar[]",
            name="formats_supported",
        ),
        CheckConstraint("source_count >= 0", name="source_count_nonnegative"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "template_mode IN ('default', 'builtin', 'uploaded')", name="template_mode_supported"
        ),
        CheckConstraint(
            "(status = 'completed' AND title_ciphertext IS NOT NULL "
            "AND content_plan_ciphertext IS NOT NULL "
            "AND source_snapshot_ciphertext IS NOT NULL AND source_count > 0 "
            "AND expires_at IS NOT NULL AND completed_at IS NOT NULL) OR status <> 'completed'",
            name="completed_state_supported",
        ),
        Index(
            "uq_generated_documents_user_client_request",
            "user_id",
            "client_request_id",
            unique=True,
        ),
        Index(
            "uq_generated_documents_user_source_message",
            "user_id",
            "source_message_id",
            unique=True,
        ),
        Index(
            "uq_generated_documents_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'generating', 'rendering')"),
        ),
        Index("ix_generated_documents_user_created", "user_id", "created_at"),
        Index("ix_generated_documents_status_lease", "status", "lease_expires_at", "created_at"),
        Index(
            "ix_generated_documents_consultation_source_created",
            "consultation_id",
            "source_message_id",
            "created_at",
        ),
        Index(
            "ix_generated_documents_expiry",
            "expires_at",
            postgresql_where=text("status = 'completed'"),
        ),
    )


class GeneratedDocumentFile(Base):
    __tablename__ = "generated_document_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(160), nullable=False)
    file_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("format IN ('docx', 'pptx')", name="format_supported"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
        Index(
            "uq_generated_document_files_generation_format",
            "generation_id",
            "format",
            unique=True,
        ),
    )


class GeneratedDocumentTemplate(Base):
    __tablename__ = "generated_document_templates"

    generation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generated_documents.id", ondelete="CASCADE"), primary_key=True
    )
    storage_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    file_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint("byte_size > 0", name="byte_size_positive"),)


class GeneratedDocumentDeletionJob(Base):
    __tablename__ = "generated_document_deletion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    storage_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'retrying', 'completed', 'failed')",
            name="status_supported",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        Index("ix_generated_document_deletion_due", "status", "next_attempt_at"),
    )
