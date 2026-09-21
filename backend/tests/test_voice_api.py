import io
import json
from fractions import Fraction

import av
import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.api.routes import voice
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import AuditLog
from app.services import upload_limits
from app.services.audio_validation import ValidatedAudio, _validate_webm_opus
from app.services.auth import ACCESS_COOKIE
from app.services.voice_transcription import transcribe_audio


@pytest.fixture(autouse=True)
def reset_voice_upload_limits():
    upload_limits._reset_upload_limits()
    yield
    upload_limits._reset_upload_limits()


def webm_opus_bytes(seconds: float = 1.0) -> bytes:
    output = io.BytesIO()
    container = av.open(output, mode="w", format="webm")
    stream = container.add_stream("libopus", rate=48_000)
    stream.layout = "mono"
    samples_per_frame = 960
    frame_count = max(1, round(seconds * 48_000 / samples_per_frame))
    for index in range(frame_count):
        frame = av.AudioFrame(format="s16", layout="mono", samples=samples_per_frame)
        frame.sample_rate = 48_000
        frame.time_base = Fraction(1, 48_000)
        frame.pts = index * samples_per_frame
        frame.planes[0].update(bytes(frame.planes[0].buffer_size))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return output.getvalue()


async def test_voice_transcription_requires_login(profile_context):
    client, _, _ = profile_context
    response = await client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("voice", webm_opus_bytes(), "audio/webm")},
    )
    assert response.status_code == 401


async def test_voice_transcription_validates_content_audits_and_never_writes_audio(
    profile_context, tmp_path, monkeypatch
):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    audio = webm_opus_bytes(1.2)

    async def fake_transcribe(validated, *, settings):
        assert validated.content == audio
        assert validated.mime_type == "audio/webm"
        assert settings.asr_model == "qwen3-asr-flash"
        return "最近三天咳嗽"

    monkeypatch.setattr(voice, "transcribe_audio", fake_transcribe)
    before = list(tmp_path.iterdir())
    response = await client.post(
        "/api/v1/voice/transcribe",
        # Declared MIME is deliberately wrong: the server must inspect bytes.
        files={"audio": ("voice", audio, "application/octet-stream")},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "最近三天咳嗽", "durationMs": 1200}
    assert response.headers["cache-control"] == "no-store"
    assert list(tmp_path.iterdir()) == before

    event = await db.scalar(
        select(AuditLog).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action == "transcribe",
        )
    )
    assert event is not None
    assert event.resource_type == "voice_audio"
    assert event.outcome == "success"
    assert event.reason_code is None


async def test_voice_multipart_over_one_megabyte_stays_in_memory(
    profile_context, monkeypatch
):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    content = webm_opus_bytes() + b"\x00" * (1200 * 1024)

    async def inspect_upload(upload, *, max_bytes, max_seconds):
        assert max_bytes == 2 * 1024 * 1024
        assert max_seconds == 60
        assert getattr(upload.file, "_rolled", None) is False
        received = await upload.read()
        await upload.close()
        assert received == content
        return ValidatedAudio(received, "audio/webm", 1000)

    async def fake_transcribe(*_args, **_kwargs):
        return "内存上传测试"

    monkeypatch.setattr(voice, "read_and_validate_audio", inspect_upload)
    monkeypatch.setattr(voice, "transcribe_audio", fake_transcribe)
    response = await client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("voice", content, "audio/webm")},
    )
    assert response.status_code == 200


async def test_voice_body_limit_rejects_before_multipart_spooling(profile_context):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("voice", b"x" * (3 * 1024 * 1024), "audio/webm")},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "VOICE_TOO_LARGE"


@pytest.mark.parametrize(
    ("content", "status", "code"),
    [
        (b"RIFF-not-webm", 415, "VOICE_TYPE_NOT_ALLOWED"),
        (b"\x1a\x45\xdf\xa3webm-corrupt", 422, "VOICE_INVALID_AUDIO"),
        (b"x" * (2 * 1024 * 1024 + 1), 413, "VOICE_TOO_LARGE"),
    ],
    ids=["unsupported-format", "corrupt-webm", "too-large"],
)
async def test_invalid_voice_audio_is_rejected_and_audited(
    profile_context, content, status, code
):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("voice", content, "audio/webm")},
    )
    assert response.status_code == status
    assert response.json()["code"] == code
    if code == "VOICE_TYPE_NOT_ALLOWED":
        assert "输入法语音输入" in response.json()["message"]

    event = await db.scalar(
        select(AuditLog).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action == "transcribe",
        )
    )
    assert event is not None
    assert event.outcome == "rejected"
    assert event.reason_code == code


def test_voice_audio_duration_is_derived_from_decoded_frames():
    valid = _validate_webm_opus(webm_opus_bytes(1.4), max_seconds=60)
    assert valid.duration_ms == 1400

    with pytest.raises(AppError) as raised:
        _validate_webm_opus(webm_opus_bytes(60.6), max_seconds=60)
    assert raised.value.code == "VOICE_TOO_LONG"


async def test_voice_provider_failure_is_audited_without_payload(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))

    async def failed_transcribe(*_args, **_kwargs):
        raise AppError(504, "VOICE_PROVIDER_TIMEOUT", "语音识别超时，请稍后再试")

    monkeypatch.setattr(voice, "transcribe_audio", failed_transcribe)
    response = await client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("voice", webm_opus_bytes(), "audio/webm")},
    )
    assert response.status_code == 504
    event = await db.scalar(
        select(AuditLog).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action == "transcribe",
        )
    )
    assert event is not None
    assert event.reason_code == "VOICE_PROVIDER_TIMEOUT"
    assert not hasattr(event, "details")


async def test_voice_rate_limit_is_per_user_and_does_not_amplify_audit(
    profile_context, monkeypatch
):
    client, db, (user, other_user) = profile_context
    monkeypatch.setitem(upload_limits.RESOURCE_UPLOAD_LIMITS, "voice_audio", 2)

    async def fake_transcribe(*_args, **_kwargs):
        return "测试语音"

    monkeypatch.setattr(voice, "transcribe_audio", fake_transcribe)
    audio = webm_opus_bytes()
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    for _ in range(2):
        assert (
            await client.post(
                "/api/v1/voice/transcribe",
                files={"audio": ("voice", audio, "audio/webm")},
            )
        ).status_code == 200
    limited = await client.post(
        "/api/v1/voice/transcribe",
        files={"audio": ("voice", audio, "audio/webm")},
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "UPLOAD_RATE_LIMITED"
    assert limited.json()["details"]["retryAfterSeconds"] > 0

    client.cookies.set(ACCESS_COOKIE, create_access_token(other_user.id))
    assert (
        await client.post(
            "/api/v1/voice/transcribe",
            files={"audio": ("voice", audio, "audio/webm")},
        )
    ).status_code == 200

    first_user_events = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.actor_user_id == user.id,
                AuditLog.action == "transcribe",
            )
        )
    ).all()
    assert len(first_user_events) == 2


async def test_qwen_asr_uses_server_key_base64_and_trims_response():
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "  最近三天咳嗽\n伴有咽痛  "}}]},
        )

    settings = get_settings().model_copy(
        update={
            "asr_api_key": None,
            "qwen_api_key": SecretStr("server-qwen-key"),
            "asr_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        }
    )
    audio = ValidatedAudio(b"webm-bytes", "audio/webm", 1000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await transcribe_audio(audio, settings=settings, client=client)

    assert text == "最近三天咳嗽 伴有咽痛"
    assert captured["authorization"] == "Bearer server-qwen-key"
    assert captured["url"] == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen3-asr-flash"
    data_uri = body["messages"][0]["content"][0]["input_audio"]["data"]
    assert data_uri.startswith("data:audio/webm;base64,")
    assert "server-qwen-key" not in json.dumps(body)


@pytest.mark.parametrize(
    ("provider_response", "status", "code"),
    [
        ({"choices": [{"message": {"content": "  "}}]}, 422, "VOICE_NO_SPEECH"),
        ({"unexpected": True}, 502, "VOICE_PROVIDER_INVALID_RESPONSE"),
    ],
)
async def test_qwen_asr_rejects_empty_or_invalid_responses(
    provider_response, status, code
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=provider_response)

    settings = get_settings().model_copy(
        update={"asr_api_key": SecretStr("asr-only-key")}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as raised:
            await transcribe_audio(
                ValidatedAudio(b"x", "audio/webm", 1000),
                settings=settings,
                client=client,
            )
    assert raised.value.status_code == status
    assert raised.value.code == code


async def test_qwen_asr_classifies_timeout_without_exposing_details():
    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("contains upstream internals", request=request)

    settings = get_settings().model_copy(
        update={"asr_api_key": SecretStr("asr-only-key")}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(AppError) as raised:
            await transcribe_audio(
                ValidatedAudio(b"x", "audio/webm", 1000),
                settings=settings,
                client=client,
            )
    assert raised.value.status_code == 504
    assert raised.value.code == "VOICE_PROVIDER_TIMEOUT"
    assert "internals" not in raised.value.message


def test_asr_configuration_rejects_non_aliyun_or_insecure_endpoints():
    settings = get_settings()
    with pytest.raises(ValidationError):
        type(settings).model_validate(
            {**settings.model_dump(), "asr_base_url": "http://example.com/v1"}
        )
