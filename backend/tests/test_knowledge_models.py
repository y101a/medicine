from pgvector.sqlalchemy import VECTOR

from app.db.base import Base
from app.models import (
    IngestionJob,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)


def test_knowledge_tables_are_registered_with_expected_boundaries():
    assert {
        KnowledgeSource.__tablename__,
        KnowledgeDocument.__tablename__,
        KnowledgeChunk.__tablename__,
        IngestionJob.__tablename__,
    }.issubset(Base.metadata.tables)

    source_fk = next(iter(KnowledgeDocument.__table__.c.source_id.foreign_keys))
    chunk_fk = next(iter(KnowledgeChunk.__table__.c.document_id.foreign_keys))
    assert source_fk.ondelete == "RESTRICT"
    assert chunk_fk.ondelete == "CASCADE"


def test_embedding_column_is_fixed_to_selected_model_dimensions():
    embedding_type = KnowledgeChunk.__table__.c.embedding.type

    assert isinstance(embedding_type, VECTOR)
    assert embedding_type.dim == 1024


def test_document_approval_and_embedding_integrity_are_database_constraints():
    document_constraints = {
        constraint.name for constraint in KnowledgeDocument.__table__.constraints
    }
    chunk_constraints = {
        constraint.name for constraint in KnowledgeChunk.__table__.constraints
    }

    assert "ck_knowledge_documents_knowledge_document_approval_requirements" in (
        document_constraints
    )
    assert "ck_knowledge_chunks_knowledge_chunk_embedding_metadata" in chunk_constraints
    assert "ck_knowledge_chunks_knowledge_chunk_embedding_dimensions" in chunk_constraints
