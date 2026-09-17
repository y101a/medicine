"""Add trigram indexes used by hybrid medical knowledge retrieval.

Revision ID: 20260914_0011
Revises: 20260912_0010
"""

from alembic import op

revision = "20260914_0011"
down_revision = "20260912_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_content_trgm "
        "ON knowledge_chunks USING gin (content gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_section_title_trgm "
        "ON knowledge_chunks USING gin (section_title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_documents_title_trgm "
        "ON knowledge_documents USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_title_trgm", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_chunks_section_title_trgm", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_content_trgm", table_name="knowledge_chunks")
    # pg_trgm may be shared by other database objects and is intentionally retained.
