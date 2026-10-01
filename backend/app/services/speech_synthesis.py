"""Strict Alibaba Model Studio Qwen-Audio-TTS adapter."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.schemas.speech import SpeechPreset, SpeechPresetListOut, SpeechPresetOut


@dataclass(frozen=True)
class _PresetConfig:
    label: str
    voice: str
    dialect: str | None = None
    instruction: str | None = None


@dataclass(frozen=True)
class SynthesizedSpeech:
    content: bytes
    request_id: str


PRESETS: dict[SpeechPreset, _PresetConfig] = {
    SpeechPreset.MANDARIN_FEMALE: _PresetConfig("普通话·自然女声", "yuxiaoyun_v3.1"),
    SpeechPreset.MANDARIN_MALE: _PresetConfig("普通话·自然男声", "anmingyuan_v3.1"),
    SpeechPreset.SHANGHAI: _PresetConfig(
        "上海话", "longanlingxin_v3.1", "shanghai", "请用上海话自然、清晰地表达"
    ),
    SpeechPreset.CANTONESE: _PresetConfig(
        "广东话", "longanhuan_v3.1", "cantonese", "请用广东话自然、清晰地表达"
    ),
    SpeechPreset.NORTHEAST: _PresetConfig(
        "东北话", "longanfengyue_v3.1", "northeast", "请用东北话自然、清晰地表达"
    ),
    SpeechPreset.CHONGQING: _PresetConfig(
        "重庆话", "longanhuan_v3.1", "chongqing", "请用重庆话自然、清晰地表达"
    ),
    SpeechPreset.SHAANXI: _PresetConfig(
        "陕西话", "longanlingxin_v3.1", "shaanxi", "请用陕西话自然、清晰地表达"
    ),
    SpeechPreset.YUNNAN: _PresetConfig(
        "云南话", "longanlingxin_v3.1", "yunnan", "请用云南话自然、清晰地表达"
    ),
    SpeechPreset.NINGBO: _PresetConfig(
        "宁波话", "longanhuan_v3.1", "ningbo", "请用宁波话自然、清晰地表达"
    ),
    SpeechPreset.GANSU: _PresetConfig(
        "甘肃话", "xunanchuan_v3.1", "gansu", "请用甘肃话自然、清晰地表达"
    ),
}


def list_speech_presets() -> SpeechPresetListOut:
    return SpeechPresetListOut(
        default=SpeechPreset.MANDARIN_FEMALE,
        items=[
            SpeechPresetOut(
                id=preset,
                label=config.label,
                language="zh-CN",
                dialect=config.dialect,
            )
            for preset, config in PRESETS.items()
        ],
    )


def _secret(settings: Settings) -> str:
    secret = settings.tts_api_key or settings.qwen_api_key
    if secret is None or not secret.get_secret_value().strip():
        raise AppError(503, "SPEECH_NOT_CONFIGURED", "语音服务尚未配置")
    return secret.get_secret_value()


def _provider_error(response: httpx.Response) -> AppError:
    if response.status_code in {401, 403}:
        return AppError(503, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    if response.status_code in {408, 504}:
        return AppError(504, "SPEECH_SERVICE_TIMEOUT", "语音生成超时，请稍后再试")
    return AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")


def _audio_url(payload: object) -> str:
    if not isinstance(payload, dict):
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    output = payload.get("output")
    if not isinstance(output, dict) or output.get("finish_reason") != "stop":
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    audio = output.get("audio")
    url = audio.get("url") if isinstance(audio, dict) else None
    if not isinstance(url, str) or not url:
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    return url


def _public_addresses(hostname: str) -> list[str]:
    return list(
        dict.fromkeys(
            item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        )
    )


async def validate_audio_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname.startswith("dashscope-result-")
        or not hostname.endswith(".oss-cn-beijing.aliyuncs.com")
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 80, 443}
        or parsed.fragment
    ):
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    try:
        addresses = await asyncio.to_thread(_public_addresses, hostname)
    except OSError as exc:
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试") from exc
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    return urlunparse(parsed._replace(scheme="https", netloc=hostname))


def _looks_like_mp3(content: bytes) -> bool:
    return content.startswith(b"ID3") or (
        len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0
    )


async def synthesize_speech(
    text: str,
    *,
    preset: SpeechPreset,
    rate: float,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> SynthesizedSpeech:
    resolved = settings or get_settings()
    config = PRESETS[preset]
    request_id = uuid4().hex
    synthesis_input: dict[str, object] = {
        "text": text,
        "voice": config.voice,
        "format": "mp3",
        "sample_rate": 24000,
        "rate": rate,
        "language_hints": ["zh"],
        "enable_aigc_tag": True,
        "aigc_propagate_id": request_id,
    }
    if config.instruction:
        synthesis_input["instruction"] = config.instruction
    payload = {"model": resolved.tts_model, "input": synthesis_input}

    timeout = httpx.Timeout(resolved.tts_timeout_seconds, connect=15)
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        try:
            response = await active.post(
                f"{resolved.tts_base_url}/services/audio/tts/SpeechSynthesizer",
                headers={
                    "Authorization": f"Bearer {_secret(resolved)}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AppError(504, "SPEECH_SERVICE_TIMEOUT", "语音生成超时，请稍后再试") from exc
        except httpx.RequestError as exc:
            raise AppError(
                502,
                "SPEECH_SERVICE_UNAVAILABLE",
                "语音服务暂时不可用，请稍后再试",
            ) from exc
        if not response.is_success:
            raise _provider_error(response)
        try:
            result_url = _audio_url(response.json())
        except ValueError as exc:
            raise AppError(
                502,
                "SPEECH_SERVICE_UNAVAILABLE",
                "语音服务暂时不可用，请稍后再试",
            ) from exc
        secure_url = await validate_audio_url(result_url)
        try:
            audio_response = await active.get(secure_url, headers={"Accept": "audio/mpeg"})
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AppError(504, "SPEECH_SERVICE_TIMEOUT", "语音生成超时，请稍后再试") from exc
        except httpx.RequestError as exc:
            raise AppError(
                502,
                "SPEECH_SERVICE_UNAVAILABLE",
                "语音服务暂时不可用，请稍后再试",
            ) from exc
    finally:
        if owns_client:
            await active.aclose()

    if audio_response.is_redirect or not audio_response.is_success:
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    declared = audio_response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > resolved.tts_max_audio_bytes:
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    content = audio_response.content
    content_type = audio_response.headers.get("content-type", "").split(";", 1)[0].lower()
    if (
        not content
        or len(content) > resolved.tts_max_audio_bytes
        or content_type not in {"audio/mpeg", "audio/mp3", "application/octet-stream"}
        or not _looks_like_mp3(content)
    ):
        raise AppError(502, "SPEECH_SERVICE_UNAVAILABLE", "语音服务暂时不可用，请稍后再试")
    return SynthesizedSpeech(content=content, request_id=request_id)
