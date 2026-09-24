"""Strict client for Alibaba Model Studio asynchronous image generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError

ProviderState = Literal["submitted", "running", "succeeded", "failed", "cancelled", "unknown"]


@dataclass(frozen=True)
class ProviderTask:
    state: ProviderState
    task_id: str
    image_url: str | None = None
    error_code: str | None = None


def _secret(settings: Settings) -> str:
    secret = settings.image_generation_api_key or settings.qwen_api_key
    if secret is None or not secret.get_secret_value().strip():
        raise AppError(
            503,
            "IMAGE_GENERATION_NOT_CONFIGURED",
            "图片生成服务尚未配置",
        )
    return secret.get_secret_value()


def _status_error(response: httpx.Response) -> AppError:
    if response.status_code in {401, 403}:
        return AppError(503, "IMAGE_GENERATION_NOT_CONFIGURED", "图片生成服务凭据不可用")
    if response.status_code == 429:
        return AppError(429, "IMAGE_GENERATION_PROVIDER_REJECTED", "图片生成服务繁忙，请稍后再试")
    if response.status_code in {408, 504}:
        return AppError(504, "IMAGE_GENERATION_PROVIDER_TIMEOUT", "图片生成服务超时")
    if 400 <= response.status_code < 500:
        return AppError(502, "IMAGE_GENERATION_PROVIDER_REJECTED", "图片生成请求被服务拒绝")
    return AppError(502, "IMAGE_GENERATION_PROVIDER_UNAVAILABLE", "图片生成服务暂时不可用")


def _json(response: httpx.Response) -> dict[str, Any]:
    if not response.is_success:
        raise _status_error(response)
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppError(
            502,
            "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE",
            "图片生成服务返回异常",
        ) from exc
    if not isinstance(payload, dict):
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    return payload


def _image_url(output: dict[str, Any]) -> str | None:
    results = output.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        value = results[0].get("url")
        if isinstance(value, str) and value:
            return value
    choices = output.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("image"), str):
                    return item["image"]
    return None


def _parse_task(payload: dict[str, Any], *, expected_task_id: str | None = None) -> ProviderTask:
    output = payload.get("output")
    if not isinstance(output, dict):
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    task_id = output.get("task_id")
    status = output.get("task_status")
    if not isinstance(task_id, str) or not task_id or not isinstance(status, str):
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    if expected_task_id is not None and task_id != expected_task_id:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    states: dict[str, ProviderState] = {
        "PENDING": "submitted",
        "RUNNING": "running",
        "SUCCEEDED": "succeeded",
        "FAILED": "failed",
        "CANCELED": "cancelled",
        "UNKNOWN": "unknown",
    }
    state = states.get(status.upper())
    if state is None:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    url = _image_url(output) if state == "succeeded" else None
    if state == "succeeded" and not url:
        raise AppError(502, "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE", "图片生成服务返回异常")
    code = payload.get("code") or output.get("code")
    return ProviderTask(
        state=state,
        task_id=task_id,
        image_url=url,
        error_code=str(code)[:64] if code else None,
    )


async def create_provider_task(
    prompt: str,
    *,
    size: str,
    negative_prompt: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> ProviderTask:
    resolved = settings or get_settings()
    payload = {
        "model": resolved.image_generation_model,
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": {
            "prompt_extend": True,
            "watermark": False,
            "n": 1,
            "negative_prompt": negative_prompt,
            "size": size,
        },
    }
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=resolved.image_generation_timeout_seconds)
    try:
        response = await active.post(
            f"{resolved.image_generation_base_url}/services/aigc/image-generation/generation",
            headers={
                "Authorization": f"Bearer {_secret(resolved)}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            json=payload,
        )
    except httpx.TimeoutException as exc:
        raise AppError(
            504, "IMAGE_GENERATION_PROVIDER_TIMEOUT", "创建图片任务超时，请勿自动重试"
        ) from exc
    except httpx.RequestError as exc:
        raise AppError(
            502, "IMAGE_GENERATION_PROVIDER_UNAVAILABLE", "图片生成服务暂时不可用"
        ) from exc
    finally:
        if owns_client:
            await active.aclose()
    return _parse_task(_json(response))


async def query_provider_task(
    task_id: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> ProviderTask:
    resolved = settings or get_settings()
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=resolved.image_generation_timeout_seconds)
    try:
        response = await active.get(
            f"{resolved.image_generation_base_url}/tasks/{quote(task_id, safe='')}",
            headers={"Authorization": f"Bearer {_secret(resolved)}"},
        )
    except httpx.TimeoutException as exc:
        raise AppError(504, "IMAGE_GENERATION_PROVIDER_TIMEOUT", "查询图片任务超时") from exc
    except httpx.RequestError as exc:
        raise AppError(
            502, "IMAGE_GENERATION_PROVIDER_UNAVAILABLE", "图片生成服务暂时不可用"
        ) from exc
    finally:
        if owns_client:
            await active.aclose()
    return _parse_task(_json(response), expected_task_id=task_id)
