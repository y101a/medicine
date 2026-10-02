"""Add the public medical knowledge graph governance layer.

只建 PostgreSQL 侧的概念/关系/证据/发布 outbox 表：Neo4j 投影（G2）不在本迁移范围内。
所有 CHECK 文本按模型元数据逐字冻结，不在迁移里 import 应用代码——迁移是历史快照，
将来新增 predicate 不能回头改写这一版约束。

Revision ID: 20261002_0028
Revises: 20261001_0027
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261002_0028"
down_revision = "20261001_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_concepts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_type", sa.String(length=24), nullable=False),
        sa.Column("canonical_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "concept_type IN ('topic', 'symptom', 'department', 'red_flag', 'self_care')",
            name=op.f("ck_graph_concepts_concept_type_supported"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name=op.f("ck_graph_concepts_status_supported"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_graph_concepts_version_positive")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concept_type", "normalized_name", name="uq_graph_concept_type_name"),
    )
    op.create_index("ix_graph_concepts_normalized_name", "graph_concepts", ["normalized_name"])
    op.create_table(
        "graph_concept_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        sa.Column("normalized_text", sa.String(length=200), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name=op.f("ck_graph_concept_aliases_status_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["graph_concepts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concept_id", "normalized_text", name="uq_graph_concept_alias_text"),
    )
    op.create_index(
        "ix_graph_concept_aliases_normalized_text", "graph_concept_aliases", ["normalized_text"]
    )
    op.create_index("ix_graph_concept_aliases_concept", "graph_concept_aliases", ["concept_id"])
    op.create_table(
        "graph_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("predicate", sa.String(length=48), nullable=False),
        sa.Column("object_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("review_decision", sa.String(length=16), nullable=False),
        sa.Column("medical_reviewed_by", sa.String(length=200), nullable=True),
        sa.Column("medical_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("extraction_source", sa.String(length=16), nullable=False),
        sa.Column("extraction_model", sa.String(length=128), nullable=True),
        sa.Column("extraction_version", sa.String(length=32), nullable=False),
        sa.Column("published_revision", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_by", sa.String(length=200), nullable=True),
        sa.Column("retire_reason", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "review_decision <> 'approved' OR (medical_reviewed_by IS NOT NULL "
            "AND medical_reviewed_at IS NOT NULL)",
            name=op.f("ck_graph_claims_approved_requires_reviewer"),
        ),
        sa.CheckConstraint(
            "predicate IN ('MAY_INCLUDE_SYMPTOM', 'HAS_RED_FLAG', 'SUGGESTS_DEPARTMENT', "
            "'HAS_SELF_CARE_TOPIC', 'RELATED_TOPIC')",
            name=op.f("ck_graph_claims_predicate_allowed"),
        ),
        sa.CheckConstraint(
            "status <> 'retired' OR (retired_at IS NOT NULL AND retired_by IS NOT NULL)",
            name=op.f("ck_graph_claims_retired_requires_reviewer"),
        ),
        sa.CheckConstraint(
            "subject_concept_id <> object_concept_id",
            name=op.f("ck_graph_claims_subjects_are_distinct"),
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'reviewed', 'published', 'retired')",
            name=op.f("ck_graph_claims_status_supported"),
        ),
        sa.CheckConstraint(
            "status <> 'published' OR (review_decision = 'approved' "
            "AND published_revision IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_graph_claims_published_requires_approval"),
        ),
        sa.CheckConstraint(
            "review_decision IN ('pending', 'approved', 'rejected', 'returned')",
            name=op.f("ck_graph_claims_review_decision_supported"),
        ),
        sa.CheckConstraint(
            "published_revision IS NULL OR status IN ('published', 'retired')",
            name=op.f("ck_graph_claims_revision_only_when_live"),
        ),
        sa.CheckConstraint(
            "published_revision IS NULL OR published_revision >= 1",
            name=op.f("ck_graph_claims_revision_positive"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('published', 'retired') OR review_decision = 'approved'",
            name=op.f("ck_graph_claims_live_requires_approval"),
        ),
        sa.CheckConstraint(
            "extraction_source IN ('rule', 'model', 'manual')",
            name=op.f("ck_graph_claims_extraction_source_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["object_concept_id"], ["graph_concepts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["subject_concept_id"], ["graph_concepts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject_concept_id", "predicate", "object_concept_id", name="uq_graph_claim_triple"
        ),
    )
    op.create_index("ix_graph_claims_predicate_status", "graph_claims", ["predicate", "status"])
    op.create_index("ix_graph_claims_status_created", "graph_claims", ["status", "created_at"])
    op.create_index(
        "ix_graph_claims_published_revision", "graph_claims", ["published_revision"]
    )
    op.create_table(
        "graph_claim_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_content_hash", sa.String(length=64), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=True),
        sa.Column("span_end", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(span_start IS NULL AND span_end IS NULL) OR (span_start IS NOT NULL "
            "AND span_end IS NOT NULL AND span_start >= 0 AND span_end > span_start)",
            name=op.f("ck_graph_claim_evidence_span_range"),
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["graph_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "chunk_id", name="uq_graph_claim_evidence_chunk"),
    )
    op.create_index("ix_graph_claim_evidence_document", "graph_claim_evidence", ["document_id"])
    op.create_index("ix_graph_claim_evidence_chunk", "graph_claim_evidence", ["chunk_id"])
    op.create_table(
        "graph_publication_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("claim_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_graph_publication_jobs_attempts_non_negative")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_graph_publication_jobs_status_supported"),
        ),
        sa.CheckConstraint(
            "target_revision >= 1",
            name=op.f("ck_graph_publication_jobs_target_revision_positive"),
        ),
        sa.CheckConstraint(
            "claim_count >= 0", name=op.f("ck_graph_publication_jobs_claim_count_non_negative")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_graph_publication_idempotency_key"),
        sa.UniqueConstraint("target_revision", name="uq_graph_publication_target_revision"),
    )
    op.create_index(
        "ix_graph_publication_jobs_status_created",
        "graph_publication_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("graph_publication_jobs")
    op.drop_table("graph_claim_evidence")
    op.drop_table("graph_claims")
    op.drop_table("graph_concept_aliases")
    op.drop_table("graph_concepts")