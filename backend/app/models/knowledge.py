import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    priority: Mapped[int] = mapped_column(Integer)
    organization: Mapped[str] = mapped_column(String(200))
    channel_name: Mapped[str] = mapped_column(String(300))
    authority_level: Mapped[str] = mapped_column(String(64))
    jurisdiction: Mapped[str] = mapped_column(String(16), default="CN")
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    entry_url: Mapped[str] = mapped_column(Text)
    legal_notice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingestion_status: Mapped[str] = mapped_column(String(32), default="candidate")
    automated_collection: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 9", name="knowledge_source_priority"),
        CheckConstraint(
            "ingestion_status IN "
            "('candidate', 'prototype', 'approved', 'blocked', 'retired')",
            name="knowledge_source_ingestion_status",
        ),
        Index("ix_knowledge_sources_status_priority", "ingestion_status", "priority"),
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT")
    )
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(500))
    responsible_department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    authors: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    content_type: Mapped[str] = mapped_column(String(32), default="web_page")
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    jurisdiction: Mapped[str] = mapped_column(String(16), default="CN")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_status: Mapped[str] = mapped_column(String(24), default="pending")
    license_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    medical_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    medical_reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True
    )
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "canonical_url",
            "content_hash",
            name="uq_knowledge_documents_source_url_hash",
        ),
        CheckConstraint(
            "review_status IN "
            "('pending', 'prototype', 'approved', 'rejected', 'superseded', 'expired')",
            name="knowledge_document_review_status",
        ),
        CheckConstraint(
            "review_status <> 'approved' OR "
            "(legal_reviewed_at IS NOT NULL AND medical_reviewed_at IS NOT NULL "
            "AND legal_reviewed_by IS NOT NULL AND medical_reviewed_by IS NOT NULL "
            "AND license_type IS NOT NULL AND content_text IS NOT NULL)",
            name="knowledge_document_approval_requirements",
        ),
        Index(
            "ix_knowledge_documents_source_review",
            "source_id",
            "review_status",
            "published_at",
        ),
        Index("ix_knowledge_documents_content_hash", "content_hash"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    section_path: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(1024), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_knowledge_chunks_document_index"
        ),
        CheckConstraint("chunk_index >= 0", name="knowledge_chunk_index_nonnegative"),
        CheckConstraint(
            "token_count IS NULL OR token_count >= 0",
            name="knowledge_chunk_token_count_nonnegative",
        ),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL "
            "AND embedding_version IS NULL AND embedding_dimensions IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL "
            "AND embedding_version IS NOT NULL AND embedding_dimensions > 0)",
            name="knowledge_chunk_embedding_metadata",
        ),
        CheckConstraint(
            "embedding IS NULL OR vector_dims(embedding) = embedding_dimensions",
            name="knowledge_chunk_embedding_dimensions",
        ),
        Index("ix_knowledge_chunks_document", "document_id", "chunk_index"),
        Index("ix_knowledge_chunks_content_hash", "content_hash"),
        Index("ix_knowledge_chunks_embedding_model", "embedding_model", "embedding_version"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(32), default="document_import")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    input_uri: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stats: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ingestion_job_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ingestion_job_time_order",
        ),
        Index("ix_ingestion_jobs_status_created", "status", "created_at"),
    )
