"""Small bounded JSON calls for optional specialist agents.

The selected consultation model and key are reused; no hidden provider or
autonomous tool access is introduced. Callers must treat output as untrusted.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.ai.provider import chat_completions_url
from app.ai.registry import ModelConfig
from app.core.config import get_settings
from app.core.errors import AppError

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


async def request_agent_json(
    model: ModelConfig,
    system_prompt: str,
    user_payload: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    payload = {
        "model": model.id,
        "stream": False,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
            },
        ],
        **model.extra_payload,
    }
    timeout = httpx.Timeout(get_settings().ai_timeout_seconds, connect=15)
    owned_client = client is None
    active = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await active.post(
            chat_completions_url(model.base_url),
            headers={"Authorization": f"Bearer {model.api_key.get_secret_value()}"},
            json=payload,
        )
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise AppError(504, "AGENT_MODEL_TIMEOUT", "协同规划模型超时") from exc
    except httpx.HTTPError as exc:
        raise AppError(502, "AGENT_MODEL_UNAVAILABLE", "协同规划模型不可用") from exc
    finally:
        if owned_client:
            await active.aclose()
    if response.status_code >= 400:
        raise AppError(502, "AGENT_MODEL_UNAVAILABLE", "协同规划模型不可用")
    try:
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or len(content) > 4000:
            raise ValueError("invalid agent content")
        parsed = json.loads(_FENCE.sub("", content.strip()).strip())
        if not isinstance(parsed, dict):
            raise ValueError("invalid agent JSON")
        return parsed
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AppError(502, "AGENT_MODEL_INVALID_RESPONSE", "协同规划模型输出无效") from exc
