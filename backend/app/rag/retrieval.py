import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.embeddings import EmbeddingBatch, EmbeddingError, embed_texts

QueryEmbedder = Callable[[list[str]], Awaitable[EmbeddingBatch]]

# 检索模式。hybrid 是线上默认行为，另两种只为「纯关键词 / 纯向量 / 混合」对比评测而存在：
#   hybrid  —— 关键词（pg_trgm word_similarity）与向量两路召回，再用 RRF 合并；
#   keyword —— 只走关键词，**完全不调用向量服务**（可零成本评测，且能验证无向量的语料）；
#   vector  —— 只走向量，忽略关键词命中。
# 两条单路都复用同一套 RRF 排序：单路时 RRF 会自然退化为该路自己的名次排序。
RetrievalMode = Literal["hybrid", "keyword", "vector"]
RETRIEVAL_MODES: tuple[RetrievalMode, ...] = ("hybrid", "keyword", "vector")
MAX_QUERY_CHARS = 500
HYBRID_CANDIDATE_LIMIT = 20
RRF_RANK_CONSTANT = 60
MIN_KEYWORD_SCORE = 0.1
SENSITIVE_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\w)"),
    re.compile(r"(?<!\d)\d{15}(?!\d)"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:姓名[:：]?|我叫)\s*[\u4e00-\u9fff·]{2,10}"),
    re.compile(r"(?:住址|详细地址|家庭地址)[:：]?[^，。；\n]{4,80}"),
)
KEYWORD_NOISE_PATTERN = re.compile(
    r"个人信息已移除|请问|我想了解|想了解|我有|我得了|最近|"
    r"可能是|可能|有哪些|有什么|症状|表现|怎么治疗|如何治疗|"
    r"怎么办|是什么|科普|介绍|一下|是否|的吗|吗|呢"
)


class RetrievalError(ValueError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class RetrievalCitation:
    chunk_id: UUID
    document_id: UUID
    source_key: str
    organization: str
    title: str
    canonical_url: str
    section_title: str | None
    version_label: str | None
    published_at: datetime | None
    content: str
    similarity: float
    trust_level: str
    keyword_score: float | None = None
    vector_similarity: float | None = None
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    query_redacted: bool
    model: str
    version: str
    items: list[RetrievalCitation]
    mode: RetrievalMode = "hybrid"


def sanitize_retrieval_query(query: str) -> tuple[str, bool]:
    normalized = unicodedata.normalize("NFKC", query).replace("\x00", " ")
    redacted = False
    for pattern in SENSITIVE_PATTERNS:
        normalized, replacements = pattern.subn(" [个人信息已移除] ", normalized)
        redacted = redacted or replacements > 0
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) > MAX_QUERY_CHARS:
        normalized = normalized[:MAX_QUERY_CHARS].rstrip()
        redacted = True
    if len(normalized.replace("[个人信息已移除]", "").strip()) < 2:
        raise RetrievalError(422, "RETRIEVAL_QUERY_EMPTY", "移除个人信息后没有可检索内容")
    return normalized, redacted


def normalize_keyword_query(query: str) -> str:
    """Reduce conversational wrappers while retaining disease names and terms."""
    normalized = KEYWORD_NOISE_PATTERN.sub(" ", query)
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", normalized)
    tokens = [token for token in normalized.split() if len(token) >= 2]
    return " ".join(tokens) or query


def _candidate_relevance(candidate: dict[str, object]) -> float:
    scores = (
        candidate["keyword_score"],
        candidate["vector_similarity"],
    )
    return max(float(score) for score in scores if score is not None)


async def search_knowledge(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = 5,
    mode: RetrievalMode = "hybrid",
    embedder: QueryEmbedder | None = None,
) -> RetrievalResult:
    if top_k < 1 or top_k > 10:
        raise RetrievalError(422, "RETRIEVAL_LIMIT_INVALID", "召回数量必须为 1-10")
    if mode not in RETRIEVAL_MODES:
        # Literal 只在类型层面约束；CLI 与评测脚本传进来的仍是运行期值。
        raise RetrievalError(
            422,
            "RETRIEVAL_MODE_INVALID",
            "检索模式只能是 hybrid、keyword 或 vector",
        )
    sanitized_query, query_redacted = sanitize_retrieval_query(query)
    keyword_query = normalize_keyword_query(sanitized_query)
    settings = get_settings()
    status_filter = and_(
        KnowledgeSource.ingestion_status == "approved",
        KnowledgeDocument.review_status == "approved",
    )
    if settings.app_environment == "development":
        status_filter = or_(
            and_(
                KnowledgeSource.ingestion_status == "approved",
                KnowledgeDocument.review_status == "approved",
            ),
            and_(
                KnowledgeSource.ingestion_status == "prototype",
                KnowledgeDocument.review_status == "prototype",
            ),
        )
    base_filters = (
        status_filter,
        or_(
            KnowledgeDocument.document_metadata["web_expires_at"].as_string().is_(None),
            KnowledgeDocument.document_metadata["web_expires_at"].as_string()
            > datetime.now(UTC).isoformat(),
        ),
    )
    vector_filters = (
        *base_filters,
        KnowledgeChunk.embedding.is_not(None),
        KnowledgeChunk.embedding_model == settings.embedding_model,
        KnowledgeChunk.embedding_version == settings.embedding_version,
        KnowledgeChunk.embedding_dimensions == settings.embedding_dimensions,
    )

    candidate_limit = max(HYBRID_CANDIDATE_LIMIT, top_k * 4)
    if mode == "vector":
        keyword_rows = []
    else:
        # Keep the operator threshold aligned with MIN_KEYWORD_SCORE so PostgreSQL can
        # use the pg_trgm GIN indexes instead of ranking every eligible row.
        await db.execute(
            text(f"SET LOCAL pg_trgm.word_similarity_threshold = {MIN_KEYWORD_SCORE}")
        )
        keyword_match = or_(
            literal(keyword_query).bool_op("<%")(KnowledgeDocument.title),
            literal(keyword_query).bool_op("<%")(
                func.coalesce(KnowledgeChunk.section_title, "")
            ),
            literal(keyword_query).bool_op("<%")(KnowledgeChunk.content),
        )
        keyword_score = func.greatest(
            func.word_similarity(keyword_query, KnowledgeDocument.title),
            func.word_similarity(
                keyword_query,
                func.coalesce(KnowledgeChunk.section_title, ""),
            ),
            func.word_similarity(keyword_query, KnowledgeChunk.content),
        ).label("keyword_score")
        keyword_statement = (
            select(KnowledgeChunk, KnowledgeDocument, KnowledgeSource, keyword_score)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(*base_filters, keyword_match, keyword_score >= MIN_KEYWORD_SCORE)
            .order_by(keyword_score.desc(), KnowledgeSource.priority, KnowledgeChunk.id)
            .limit(candidate_limit)
        )
        keyword_rows = (await db.execute(keyword_statement)).all()

    if mode == "keyword":
        vector_rows = []
    else:
        eligible_chunk_id = await db.scalar(
            select(KnowledgeChunk.id)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(*vector_filters)
            .limit(1)
        )
        if eligible_chunk_id is None:
            vector_rows = []
        else:
            try:
                embedding_batch = await (embedder or embed_texts)([sanitized_query])
            except EmbeddingError as exc:
                status_code = 504 if exc.code == "EMBEDDING_TIMEOUT" else 502
                raise RetrievalError(status_code, exc.code, str(exc)) from exc
            if len(embedding_batch.vectors) != 1:
                raise RetrievalError(
                    502, "EMBEDDING_RESPONSE_INVALID", "查询向量数量不一致"
                )
            query_vector = embedding_batch.vectors[0]
            if len(query_vector) != settings.embedding_dimensions:
                raise RetrievalError(
                    502, "EMBEDDING_DIMENSION_MISMATCH", "查询向量维度不一致"
                )

            distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label(
                "cosine_distance"
            )
            vector_statement = (
                select(KnowledgeChunk, KnowledgeDocument, KnowledgeSource, distance)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .join(
                    KnowledgeSource,
                    KnowledgeSource.id == KnowledgeDocument.source_id,
                )
                .where(*vector_filters)
                .order_by(distance, KnowledgeSource.priority, KnowledgeChunk.id)
                .limit(candidate_limit)
            )
            vector_rows = (await db.execute(vector_statement)).all()

    candidates: dict[UUID, dict[str, object]] = {}
    for rank, (chunk, document, source, score) in enumerate(keyword_rows, start=1):
        candidates[chunk.id] = {
            "chunk": chunk,
            "document": document,
            "source": source,
            "keyword_score": float(score),
            "vector_similarity": None,
            "rrf_score": 1.0 / (RRF_RANK_CONSTANT + rank),
        }
    for rank, (chunk, document, source, row_distance) in enumerate(
        vector_rows,
        start=1,
    ):
        vector_similarity = max(-1.0, min(1.0, 1.0 - float(row_distance)))
        candidate = candidates.setdefault(
            chunk.id,
            {
                "chunk": chunk,
                "document": document,
                "source": source,
                "keyword_score": None,
                "vector_similarity": None,
                "rrf_score": 0.0,
            },
        )
        candidate["vector_similarity"] = vector_similarity
        candidate["rrf_score"] = float(candidate["rrf_score"]) + 1.0 / (
            RRF_RANK_CONSTANT + rank
        )

    ranked_candidates = sorted(
        candidates.values(),
        key=lambda item: (
            -float(item["rrf_score"]),
            -_candidate_relevance(item),
            str(item["chunk"].id),
        ),
    )[:top_k]
    items = []
    for candidate in ranked_candidates:
        chunk = candidate["chunk"]
        document = candidate["document"]
        source = candidate["source"]
        keyword_relevance = candidate["keyword_score"]
        vector_relevance = candidate["vector_similarity"]
        compatibility_similarity = (
            vector_relevance if vector_relevance is not None else keyword_relevance
        )
        assert compatibility_similarity is not None
        items.append(
            RetrievalCitation(
                chunk_id=chunk.id,
                document_id=document.id,
                source_key=source.source_key,
                organization=source.organization,
                title=document.title,
                canonical_url=document.canonical_url,
                section_title=chunk.section_title,
                version_label=document.version_label,
                published_at=document.published_at,
                content=chunk.content,
                # Preserve the historical cosine meaning whenever a vector exists.
                similarity=round(
                    max(-1.0, min(1.0, float(compatibility_similarity))),
                    6,
                ),
                trust_level=(
                    "approved"
                    if document.review_status == "approved"
                    else "prototype"
                ),
                keyword_score=(
                    round(float(keyword_relevance), 6)
                    if keyword_relevance is not None
                    else None
                ),
                vector_similarity=(
                    round(float(vector_relevance), 6)
                    if vector_relevance is not None
                    else None
                ),
                rerank_score=round(float(candidate["rrf_score"]), 8),
            )
        )
    return RetrievalResult(
        query_redacted=query_redacted,
        model=settings.embedding_model,
        version=settings.embedding_version,
        items=items,
        mode=mode,
    )
