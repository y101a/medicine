"""Fix knowledge chunk embeddings to the selected 1024 dimensions."""

from alembic import op

revision = "20260911_0008"
down_revision = "20260911_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL AND vector_dims(embedding) <> 1024
            ) THEN
                RAISE EXCEPTION
                    'knowledge_chunks contains embeddings that are not 1024-dimensional';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE knowledge_chunks
        ALTER COLUMN embedding TYPE vector(1024)
        USING embedding::vector(1024)
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE knowledge_chunks
        ALTER COLUMN embedding TYPE vector
        USING embedding::vector
        """
    )
