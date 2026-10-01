"""Add isolated encrypted user private knowledge base tables.

Revision ID: 20261001_0027
Revises: 20260928_0026
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261001_0027"
down_revision = "20260928_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "private_knowledge_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name_ciphertext", sa.Text(), nullable=False),
        sa.Column("name_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("description_ciphertext", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'deleting')",
            name=op.f("ck_private_knowledge_collections_status_supported"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name_fingerprint", name="uq_private_kb_collection_name"),
    )
    op.create_index(
        "ix_private_kb_collections_user_created",
        "private_knowledge_collections",
        ["user_id", "created_at", "id"],
    )
    op.create_table(
        "private_knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name_ciphertext", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("content_hash_hmac", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("index_version", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('pdf', 'docx', 'pptx', 'txt', 'md')",
            name=op.f("ck_private_knowledge_documents_kind_supported"),
        ),
        sa.CheckConstraint(
            "byte_size BETWEEN 1 AND 31457280",
            name=op.f("ck_private_knowledge_documents_byte_size_supported"),
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count BETWEEN 1 AND 100",
            name=op.f("ck_private_knowledge_documents_page_count_supported"),
        ),
        sa.CheckConstraint(
            "char_count BETWEEN 1 AND 500000",
            name=op.f("ck_private_knowledge_documents_char_count_supported"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'parsing', 'indexing', 'ready', 'failed', 'deleting')",
            name=op.f("ck_private_knowledge_documents_status_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["private_knowledge_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "collection_id", "content_hash_hmac", name="uq_private_kb_document_hash"
        ),
    )
    op.create_index(
        "ix_private_kb_documents_user_collection_created",
        "private_knowledge_documents",
        ["user_id", "collection_id", "created_at", "id"],
    )
    op.create_table(
        "private_knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(length=64), nullable=False),
        sa.Column("content_ciphertext", sa.Text(), nullable=False),
        sa.Column("content_hash_hmac", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_private_knowledge_chunks_position_nonnegative")
        ),
        sa.CheckConstraint(
            "char_count BETWEEN 1 AND 4000",
            name=op.f("ck_private_knowledge_chunks_char_count_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["private_knowledge_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "position", name="uq_private_kb_chunks_position"),
    )
    op.create_index(
        "ix_private_kb_chunks_user_document",
        "private_knowledge_chunks",
        ["user_id", "document_id", "position"],
    )
    op.create_table(
        "private_knowledge_search_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("term_hmac", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["private_knowledge_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id", "term_hmac", name="uq_private_kb_search_term"),
    )
    op.create_index(
        "ix_private_kb_search_terms_user_term",
        "private_knowledge_search_terms",
        ["user_id", "term_hmac", "chunk_id"],
    )
    op.create_table(
        "message_private_knowledge_selections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 2",
            name=op.f("ck_message_private_knowledge_selections_position_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["private_knowledge_collections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "collection_id", name="uq_message_private_kb_selection_collection"
        ),
        sa.UniqueConstraint(
            "message_id", "position", name="uq_message_private_kb_selection_position"
        ),
    )
    op.create_index(
        "ix_message_private_kb_selections_message",
        "message_private_knowledge_selections",
        ["message_id", "position"],
    )
    op.create_table(
        "message_private_knowledge_citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reference_number", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(length=64), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "reference_number BETWEEN 1 AND 5",
            name=op.f("ck_message_private_knowledge_citations_reference_number_supported"),
        ),
        sa.CheckConstraint(
            "similarity BETWEEN 0 AND 1",
            name=op.f("ck_message_private_knowledge_citations_similarity_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["private_knowledge_documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "reference_number", name="uq_message_private_kb_citation_number"
        ),
    )
    op.create_index(
        "ix_message_private_kb_citations_message",
        "message_private_knowledge_citations",
        ["message_id", "reference_number"],
    )


def downgrade() -> None:
    op.drop_table("message_private_knowledge_citations")
    op.drop_table("message_private_knowledge_selections")
    op.drop_table("private_knowledge_search_terms")
    op.drop_table("private_knowledge_chunks")
    op.drop_table("private_knowledge_documents")
    op.drop_table("private_knowledge_collections")
