import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
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


class PrivateKnowledgeCollection(Base):
    __tablename__ = "private_knowledge_collections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    name_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    description_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name_fingerprint", name="uq_private_kb_collection_name"),
        CheckConstraint("status IN ('active', 'deleting')", name="status_supported"),
        Index("ix_private_kb_collections_user_created", "user_id", "created_at", "id"),
    )


class PrivateKnowledgeDocument(Base):
    __tablename__ = "private_knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("private_knowledge_collections.id", ondelete="CASCADE"), nullable=False
    )
    display_name_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="indexing")
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    index_version: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "collection_id", "content_hash_hmac", name="uq_private_kb_document_hash"
        ),
        CheckConstraint("kind IN ('pdf', 'docx', 'pptx', 'txt', 'md')", name="kind_supported"),
        CheckConstraint("byte_size BETWEEN 1 AND 31457280", name="byte_size_supported"),
        CheckConstraint(
            "page_count IS NULL OR page_count BETWEEN 1 AND 100",
            name="page_count_supported",
        ),
        CheckConstraint("char_count BETWEEN 1 AND 500000", name="char_count_supported"),
        CheckConstraint(
            "status IN ('queued', 'parsing', 'indexing', 'ready', 'failed', 'deleting')",
            name="status_supported",
        ),
        Index(
            "ix_private_kb_documents_user_collection_created",
            "user_id",
            "collection_id",
            "created_at",
            "id",
        ),
    )


class PrivateKnowledgeChunk(Base):
    __tablename__ = "private_knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("private_knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[str] = mapped_column(String(64), nullable=False)
    content_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("document_id", "position", name="uq_private_kb_chunks_position"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint("char_count BETWEEN 1 AND 4000", name="char_count_supported"),
        Index("ix_private_kb_chunks_user_document", "user_id", "document_id", "position"),
    )


class PrivateKnowledgeSearchTerm(Base):
    __tablename__ = "private_knowledge_search_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("private_knowledge_chunks.id", ondelete="CASCADE"), nullable=False
    )
    term_hmac: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("chunk_id", "term_hmac", name="uq_private_kb_search_term"),
        Index("ix_private_kb_search_terms_user_term", "user_id", "term_hmac", "chunk_id"),
    )


class MessagePrivateKnowledgeSelection(Base):
    __tablename__ = "message_private_knowledge_selections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("private_knowledge_collections.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "position", name="uq_message_private_kb_selection_position"),
        UniqueConstraint(
            "message_id", "collection_id", name="uq_message_private_kb_selection_collection"
        ),
        CheckConstraint("position BETWEEN 0 AND 2", name="position_supported"),
        Index("ix_message_private_kb_selections_message", "message_id", "position"),
    )


class MessagePrivateKnowledgeCitation(Base):
    __tablename__ = "message_private_knowledge_citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("private_knowledge_documents.id", ondelete="SET NULL"), nullable=True
    )
    reference_number: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[str] = mapped_column(String(64), nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "message_id", "reference_number", name="uq_message_private_kb_citation_number"
        ),
        CheckConstraint("reference_number BETWEEN 1 AND 5", name="reference_number_supported"),
        CheckConstraint("similarity BETWEEN 0 AND 1", name="similarity_supported"),
        Index("ix_message_private_kb_citations_message", "message_id", "reference_number"),
    )
