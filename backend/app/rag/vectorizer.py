import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.embeddings import EmbeddingBatch, EmbeddingError, embed_texts

Embedder = Callable[[list[str]], Awaitable[EmbeddingBatch]]


class ControlledVectorizationError(ValueError):
    """A safe, user-facing failure from a controlled vectorization task."""


@dataclass(frozen=True, slots=True)
class VectorizationResult:
    document_id: UUID
    chunk_count: int
    duplicate: bool
    model: str
    version: str
    dimensions: int
    total_tokens: int | None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_batch(batch: EmbeddingBatch, expected: int, dimensions: int) -> None:
    if len(batch.vectors) != expected:
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量服务返回数量不一致")
    if any(len(vector) != dimensions for vector in batch.vectors):
        raise EmbeddingError(
            "EMBEDDING_DIMENSION_MISMATCH",
            f"向量服务返回维度不是 {dimensions}",
        )


async def vectorize_document(
    db: AsyncSession,
    document_id: UUID,
    *,
    embedder: Embedder | None = None,
) -> VectorizationResult:
    settings = get_settings()
    status_filter = and_(
        KnowledgeDocument.review_status == "approved",
        KnowledgeSource.ingestion_status == "approved",
    )
    if settings.app_environment == "development":
        status_filter = or_(
            status_filter,
            and_(
                KnowledgeDocument.review_status == "prototype",
                KnowledgeSource.ingestion_status == "prototype",
            ),
        )
    document = await db.scalar(
        select(KnowledgeDocument)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
        .where(
            KnowledgeDocument.id == document_id,
            status_filter,
        )
    )
    if document is None:
        raise ControlledVectorizationError("文档不存在、已被替代或当前环境不允许使用")

    chunks = list(
        await db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document.id)
            .order_by(KnowledgeChunk.chunk_index)
        )
    )
    if not chunks:
        raise ControlledVectorizationError("文档没有可向量化的文本块")

    already_complete = all(
        chunk.embedding is not None
        and chunk.embedding_model == settings.embedding_model
        and chunk.embedding_version == settings.embedding_version
        and chunk.embedding_dimensions == settings.embedding_dimensions
        for chunk in chunks
    )
    if already_complete:
        return VectorizationResult(
            document.id,
            len(chunks),
            True,
            settings.embedding_model,
            settings.embedding_version,
            settings.embedding_dimensions,
            None,
        )

    chunk_fingerprint = "\n".join(chunk.content_hash for chunk in chunks)
    idempotency_key = _sha256(
        f"{document.id}\n{settings.embedding_model}\n{settings.embedding_version}"
        f"\n{settings.embedding_dimensions}\n{chunk_fingerprint}"
    )
    job = await db.scalar(
        select(IngestionJob).where(IngestionJob.idempotency_key == idempotency_key)
    )
    now = datetime.now(UTC)
    if job is None:
        job = IngestionJob(
            idempotency_key=idempotency_key,
            source_id=document.source_id,
            document_id=document.id,
            job_type="embedding_generation",
            status="running",
            input_uri=f"document://{document.id}",
            parser_version=settings.embedding_version,
            started_at=now,
        )
        db.add(job)
    else:
        job.status = "running"
        job.error_code = None
        job.error_message = None
        job.started_at = now
        job.finished_at = None
    await db.flush()

    resolved_embedder = embedder or embed_texts
    vectors: list[list[float]] = []
    total_tokens: int | None = 0
    try:
        for start in range(0, len(chunks), settings.embedding_batch_size):
            batch_chunks = chunks[start : start + settings.embedding_batch_size]
            batch = await resolved_embedder([chunk.content for chunk in batch_chunks])
            _validate_batch(batch, len(batch_chunks), settings.embedding_dimensions)
            vectors.extend(batch.vectors)
            if total_tokens is not None:
                total_tokens = (
                    total_tokens + batch.total_tokens
                    if batch.total_tokens is not None
                    else None
                )

        async with db.begin_nested():
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_model = settings.embedding_model
                chunk.embedding_version = settings.embedding_version
                chunk.embedding_dimensions = settings.embedding_dimensions
            job.status = "succeeded"
            job.stats = {
                "chunk_count": len(chunks),
                "model": settings.embedding_model,
                "version": settings.embedding_version,
                "dimensions": settings.embedding_dimensions,
                "total_tokens": total_tokens,
            }
            job.finished_at = datetime.now(UTC)
            await db.flush()
    except Exception as exc:
        job.status = "failed"
        job.error_code = (
            exc.code if isinstance(exc, EmbeddingError) else "EMBEDDING_GENERATION_FAILED"
        )
        job.error_message = str(exc)[:1000]
        job.finished_at = datetime.now(UTC)
        await db.flush()
        if isinstance(exc, EmbeddingError):
            raise ControlledVectorizationError(str(exc)) from exc
        raise ControlledVectorizationError("向量化失败，未写入任何不完整向量") from exc

    return VectorizationResult(
        document.id,
        len(chunks),
        False,
        settings.embedding_model,
        settings.embedding_version,
        settings.embedding_dimensions,
        total_tokens,
    )
