"""公共医学知识图谱的治理层模型（PostgreSQL 是事实源，Neo4j 只是可重建投影）。

对应 `NEO4J_KNOWLEDGE_GRAPH_PLAN.md` 第 5–6 节。三条硬边界写进 schema 本身：

1. **只放公共、已审核的医学知识**：本模块所有表都不引用 `users` / `health_records` /
   `private_knowledge_*`，证据只能指向公共 `knowledge_chunks`；外键清单由
   `tests/test_knowledge_graph_governance.py` 钉死。
2. **每条已发布事实必须有有效证据**：`graph_claims` 自身的 CHECK 保证「published 必须已审核」，
   证据是否存在由服务层在发布时重新校验（同一事务内）。
3. **状态只能取冻结值**：状态与 predicate 白名单来自本模块的枚举，CHECK 约束由枚举生成，
   因此常量与数据库约束不会各自漂移。
"""

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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConceptType(StrEnum):
    """概念类型（G0 冻结，五类，不按疾病无限扩张）。"""

    TOPIC = "topic"
    SYMPTOM = "symptom"
    DEPARTMENT = "department"
    RED_FLAG = "red_flag"
    SELF_CARE = "self_care"


class GraphConceptStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class GraphClaimPredicate(StrEnum):
    """第一批允许的关系类型（G0 冻结）。

    刻意避开 `CAUSES` / `DIAGNOSES` / `TREATS` 这类会被读成确定医疗结论的词。
    """

    MAY_INCLUDE_SYMPTOM = "MAY_INCLUDE_SYMPTOM"
    HAS_RED_FLAG = "HAS_RED_FLAG"
    SUGGESTS_DEPARTMENT = "SUGGESTS_DEPARTMENT"
    HAS_SELF_CARE_TOPIC = "HAS_SELF_CARE_TOPIC"
    RELATED_TOPIC = "RELATED_TOPIC"


class GraphClaimStatus(StrEnum):
    """候选 → 已审核 → 已发布 → 已撤回（G0 冻结）。"""

    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    PUBLISHED = "published"
    RETIRED = "retired"


class GraphReviewDecision(StrEnum):
    """医学审核结论。拒绝与退回**不**改变 `GraphClaimStatus`，它们只否掉「已审核」。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"


class GraphExtractionSource(StrEnum):
    RULE = "rule"
    MODEL = "model"
    MANUAL = "manual"


class GraphPublicationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


def sql_in_values(enum_type: type[StrEnum]) -> str:
    """把枚举成员渲染成 SQL `IN` 列表，供 CHECK 约束使用（唯一事实源）。"""

    return ", ".join(f"'{member.value}'" for member in enum_type)


class GraphConcept(Base):
    """公共医学概念。删除用 retired，避免历史引用漂移。"""

    __tablename__ = "graph_concepts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_type: Mapped[str] = mapped_column(String(24), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GraphConceptStatus.ACTIVE
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"concept_type IN ({sql_in_values(ConceptType)})", name="concept_type_supported"
        ),
        CheckConstraint(
            f"status IN ({sql_in_values(GraphConceptStatus)})", name="status_supported"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint("concept_type", "normalized_name", name="uq_graph_concept_type_name"),
        Index("ix_graph_concepts_normalized_name", "normalized_name"),
    )


class GraphConceptAlias(Base):
    """别名：必须来自审核资料或人工维护。

    `normalized_text` **只做普通索引、不做全局唯一**：同一个词可以同时是「症状」和
    「自我照护主题」，解析时按 plan 第 8.1 节模板返回最多 5 个候选，而不是让先登记的概念
    把词独占。同一个概念下的重复别名才被唯一约束挡住。
    """

    __tablename__ = "graph_concept_aliases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_concepts.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GraphConceptStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({sql_in_values(GraphConceptStatus)})", name="status_supported"
        ),
        UniqueConstraint("concept_id", "normalized_text", name="uq_graph_concept_alias_text"),
        Index("ix_graph_concept_aliases_normalized_text", "normalized_text"),
        Index("ix_graph_concept_aliases_concept", "concept_id"),
    )


class GraphClaim(Base):
    """一条医学关系（三元组 + 审核与发布状态）。

    证据放在 `graph_claim_evidence`，所以一条关系可以绑多份来源；同一对概念的同一 predicate
    只保留一条 claim（不同语境用多条证据表达），避免同一断言被重复建节点。
    """

    __tablename__ = "graph_claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_concepts.id", ondelete="RESTRICT"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(String(48), nullable=False)
    object_concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_concepts.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GraphClaimStatus.CANDIDATE
    )
    review_decision: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GraphReviewDecision.PENDING
    )
    medical_reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    medical_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GraphExtractionSource.RULE
    )
    extraction_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extraction_version: Mapped[str] = mapped_column(String(32), nullable=False)
    published_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"predicate IN ({sql_in_values(GraphClaimPredicate)})", name="predicate_allowed"
        ),
        CheckConstraint(f"status IN ({sql_in_values(GraphClaimStatus)})", name="status_supported"),
        CheckConstraint(
            f"review_decision IN ({sql_in_values(GraphReviewDecision)})",
            name="review_decision_supported",
        ),
        CheckConstraint(
            f"extraction_source IN ({sql_in_values(GraphExtractionSource)})",
            name="extraction_source_supported",
        ),
        CheckConstraint("subject_concept_id <> object_concept_id", name="subjects_are_distinct"),
        CheckConstraint(
            "published_revision IS NULL OR published_revision >= 1", name="revision_positive"
        ),
        # 已审核必须留下人和时间；发布必须已审核且有 revision。
        CheckConstraint(
            "review_decision <> 'approved' OR "
            "(medical_reviewed_by IS NOT NULL AND medical_reviewed_at IS NOT NULL)",
            name="approved_requires_reviewer",
        ),
        CheckConstraint(
            "status <> 'published' OR "
            "(review_decision = 'approved' AND published_revision IS NOT NULL "
            "AND published_at IS NOT NULL)",
            name="published_requires_approval",
        ),
        CheckConstraint(
            "status NOT IN ('published', 'retired') OR review_decision = 'approved'",
            name="live_requires_approval",
        ),
        CheckConstraint(
            "status <> 'retired' OR (retired_at IS NOT NULL AND retired_by IS NOT NULL)",
            name="retired_requires_reviewer",
        ),
        CheckConstraint(
            "published_revision IS NULL OR status IN ('published', 'retired')",
            name="revision_only_when_live",
        ),
        UniqueConstraint(
            "subject_concept_id",
            "predicate",
            "object_concept_id",
            name="uq_graph_claim_triple",
        ),
        Index("ix_graph_claims_predicate_status", "predicate", "status"),
        Index("ix_graph_claims_status_created", "status", "created_at"),
        Index("ix_graph_claims_published_revision", "published_revision"),
    )


class GraphClaimEvidence(Base):
    """claim 与公共知识块的多对多：发布前至少要有一条仍有效的证据。

    只保存定位（chunk 与字符区间）与当时的 `content_hash`，**不复制正文**：正文始终由
    PostgreSQL 的 `knowledge_chunks` 提供。哈希不一致说明知识块已被改写，需要重新审核。
    """

    __tablename__ = "graph_claim_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("graph_claims.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(span_start IS NULL AND span_end IS NULL) OR "
            "(span_start IS NOT NULL AND span_end IS NOT NULL AND span_start >= 0 "
            "AND span_end > span_start)",
            name="span_range",
        ),
        UniqueConstraint("claim_id", "chunk_id", name="uq_graph_claim_evidence_chunk"),
        Index("ix_graph_claim_evidence_document", "document_id"),
        Index("ix_graph_claim_evidence_chunk", "chunk_id"),
    )


class GraphPublicationJob(Base):
    """发布 outbox：PG 事务内登记「期望 revision」，Neo4j worker 按 revision 幂等投影。

    只保存发布编排信息，**不保存用户问题、聊天内容或私人资料**。
    """

    __tablename__ = "graph_publication_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    target_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GraphPublicationStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({sql_in_values(GraphPublicationStatus)})", name="status_supported"
        ),
        CheckConstraint("target_revision >= 1", name="target_revision_positive"),
        CheckConstraint("claim_count >= 0", name="claim_count_non_negative"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        UniqueConstraint("idempotency_key", name="uq_graph_publication_idempotency_key"),
        UniqueConstraint("target_revision", name="uq_graph_publication_target_revision"),
        Index("ix_graph_publication_jobs_status_created", "status", "created_at"),
    )