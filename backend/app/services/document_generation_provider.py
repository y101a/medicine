"""Server-controlled structured content generation for DOCX/PPTX."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.ai.provider import chat_completions_url
from app.core.config import get_settings
from app.core.errors import AppError

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


async def request_document_plan(
    system_prompt: str,
    user_payload: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    secret = settings.document_generation_api_key or settings.qwen_api_key
    if secret is None or not secret.get_secret_value().strip():
        raise AppError(
            503,
            "DOCUMENT_GENERATION_NOT_CONFIGURED",
            "文档生成服务尚未配置",
        )
    payload = {
        "model": settings.document_generation_model,
        "stream": False,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
            },
        ],
        "enable_thinking": False,
    }
    timeout = httpx.Timeout(settings.document_generation_timeout_seconds, connect=15)
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await active.post(
                chat_completions_url(settings.document_generation_base_url),
                headers={
                    "Authorization": f"Bearer {secret.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AppError(504, "DOCUMENT_MODEL_TIMEOUT", "文档内容生成超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise AppError(502, "DOCUMENT_MODEL_UNAVAILABLE", "文档内容模型暂时不可用") from exc
    finally:
        if owns_client:
            await active.aclose()
    if response.status_code >= 400:
        raise AppError(502, "DOCUMENT_MODEL_UNAVAILABLE", "文档内容模型暂时不可用")
    try:
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError
        parsed = json.loads(_FENCE.sub("", content.strip()).strip())
        if not isinstance(parsed, dict):
            raise TypeError
        return parsed
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AppError(
            502,
            "DOCUMENT_MODEL_INVALID_RESPONSE",
            "文档内容模型返回的结构无法使用",
        ) from exc
