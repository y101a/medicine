import math
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings


class EmbeddingError(RuntimeError):
    """A classified provider or response validation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    total_tokens: int | None


def embeddings_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/embeddings"):
        return normalized
    return f"{normalized}/embeddings"


def _validate_inputs(texts: list[str], settings: Settings) -> None:
    if not texts or len(texts) > settings.embedding_batch_size:
        raise EmbeddingError(
            "EMBEDDING_INPUT_INVALID",
            f"单批向量文本数量必须为 1-{settings.embedding_batch_size} 条",
        )
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise EmbeddingError("EMBEDDING_INPUT_INVALID", "向量文本不能为空")


def _parse_response(response: httpx.Response, expected: int, dimensions: int) -> EmbeddingBatch:
    try:
        body = response.json()
        rows = body["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量服务返回格式无效") from exc
    if not isinstance(rows, list) or len(rows) != expected:
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量服务返回数量不一致")

    indexed_vectors: dict[int, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量数据项格式无效")
        index = row.get("index")
        vector = row.get("embedding")
        if not isinstance(index, int) or isinstance(index, bool):
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量数据缺少有效索引")
        if index in indexed_vectors or index < 0 or index >= expected:
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量数据索引不合法")
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise EmbeddingError(
                "EMBEDDING_DIMENSION_MISMATCH",
                f"向量服务返回维度不是 {dimensions}",
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in vector
        ):
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量包含无效数值")
        indexed_vectors[index] = [float(value) for value in vector]

    if set(indexed_vectors) != set(range(expected)):
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "向量数据索引不完整")
    usage = body.get("usage")
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    if not isinstance(total_tokens, int) or isinstance(total_tokens, bool):
        total_tokens = None
    return EmbeddingBatch(
        vectors=[indexed_vectors[index] for index in range(expected)],
        total_tokens=total_tokens,
    )


async def _request_embeddings(
    client: httpx.AsyncClient,
    texts: list[str],
    settings: Settings,
) -> EmbeddingBatch:
    api_key = settings.qwen_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise EmbeddingError("EMBEDDING_NOT_CONFIGURED", "尚未配置 QWEN_API_KEY")
    try:
        response = await client.post(
            embeddings_url(settings.qwen_base_url),
            headers={
                "Authorization": f"Bearer {api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.embedding_model,
                "input": texts,
                "dimensions": settings.embedding_dimensions,
                "encoding_format": "float",
            },
        )
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise EmbeddingError("EMBEDDING_TIMEOUT", "阿里云向量服务响应超时") from exc
    except httpx.HTTPError as exc:
        raise EmbeddingError("EMBEDDING_UNAVAILABLE", "无法连接阿里云向量服务") from exc

    if response.status_code == 429:
        raise EmbeddingError("EMBEDDING_RATE_LIMITED", "阿里云向量服务请求过多")
    if response.status_code in {401, 403}:
        raise EmbeddingError("EMBEDDING_AUTH_FAILED", "阿里云向量服务认证失败")
    if response.status_code >= 400:
        raise EmbeddingError("EMBEDDING_PROVIDER_ERROR", "阿里云向量服务调用失败")
    return _parse_response(response, len(texts), settings.embedding_dimensions)


async def embed_texts(
    texts: list[str],
    *,
    client: httpx.AsyncClient | None = None,
    settings: Settings | None = None,
) -> EmbeddingBatch:
    resolved_settings = settings or get_settings()
    _validate_inputs(texts, resolved_settings)
    if client is not None:
        return await _request_embeddings(client, texts, resolved_settings)

    timeout = httpx.Timeout(resolved_settings.embedding_timeout_seconds, connect=10)
    async with httpx.AsyncClient(timeout=timeout) as owned_client:
        return await _request_embeddings(owned_client, texts, resolved_settings)
