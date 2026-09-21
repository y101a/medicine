import base64
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services.audio_validation import ValidatedAudio

MAX_TRANSCRIPT_CHARS = 4000


def _transcription_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _extract_transcript(payload: object) -> str:
    if not isinstance(payload, dict):
        raise AppError(502, "VOICE_PROVIDER_INVALID_RESPONSE", "语音识别服务返回异常")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AppError(502, "VOICE_PROVIDER_INVALID_RESPONSE", "语音识别服务返回异常")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise AppError(502, "VOICE_PROVIDER_INVALID_RESPONSE", "语音识别服务返回异常")
    text = " ".join(message["content"].split())
    if not text:
        raise AppError(422, "VOICE_NO_SPEECH", "没有识别到清晰语音，请重新录制")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise AppError(502, "VOICE_PROVIDER_INVALID_RESPONSE", "语音识别结果异常，请重试")
    return text


async def transcribe_audio(
    audio: ValidatedAudio,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    resolved = settings or get_settings()
    secret = resolved.asr_api_key or resolved.qwen_api_key
    if not secret or not secret.get_secret_value().strip():
        raise AppError(503, "VOICE_NOT_CONFIGURED", "语音识别服务尚未配置")

    encoded = base64.b64encode(audio.content).decode("ascii")
    request_body: dict[str, Any] = {
        "model": resolved.asr_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:{audio.mime_type};base64,{encoded}",
                        },
                    }
                ],
            }
        ],
        "stream": False,
        "asr_options": {"enable_itn": False},
    }

    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=resolved.asr_timeout_seconds)
    try:
        response = await active_client.post(
            _transcription_url(resolved.asr_base_url),
            headers={
                "Authorization": f"Bearer {secret.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
    except httpx.TimeoutException as exc:
        raise AppError(504, "VOICE_PROVIDER_TIMEOUT", "语音识别超时，请稍后再试") from exc
    except httpx.RequestError as exc:
        raise AppError(502, "VOICE_PROVIDER_FAILED", "语音识别服务暂时不可用，请稍后再试") from exc
    finally:
        if owns_client:
            await active_client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        raise AppError(502, "VOICE_PROVIDER_FAILED", "语音识别服务暂时不可用，请稍后再试")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppError(502, "VOICE_PROVIDER_INVALID_RESPONSE", "语音识别服务返回异常") from exc
    return _extract_transcript(payload)
