import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.api.routes import speech
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import AuditLog
from app.schemas.speech import SpeechPreset
from app.services import consultations
from app.services.auth import ACCESS_COOKIE
from app.services.speech_intent import speech_output_request
from app.services.speech_synthesis import (
    SynthesizedSpeech,
    synthesize_speech,
    validate_audio_url,
)
from app.services.speech_text import prepare_speech_text


async def _create_answer(
    profile_context,
    *,
    content: str = "## 情况梳理\n建议先休息。\n\n以上仅供健康科普参考，不替代医生面诊。",
    generation_status: str = "completed",
):
    client, db, (user, other_user) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    consultation = (
        await client.post(
            "/api/v1/consultations",
            json={"clientRequestId": str(uuid4())},
        )
    ).json()
    user_message = (
        await client.post(
            f"/api/v1/consultations/{consultation['id']}/messages",
            json={"clientRequestId": str(uuid4()), "content": "最近头痛"},
        )
    ).json()
    answer = await consultations.append_assistant_message(
        db,
        user.id,
        consultation["id"],
        uuid4(),
        content,
        "qwen",
        "qwen3.8-flash",
        "科普助手通义千问 Qwen3.8 Flash",
        generation_status=generation_status,
        medical_content=True,
    )
    return client, db, user, other_user, consultation, user_message, answer


async def test_speech_presets_require_login_and_hide_provider_fields(profile_context):
    client, _, (user, _) = profile_context
    assert (await client.get("/api/v1/speech/presets")).status_code == 401
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.get("/api/v1/speech/presets")
    assert response.status_code == 200
    payload = response.json()
    assert payload["default"] == "mandarin_female"
    assert len(payload["items"]) == 10
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for hidden in ("voice", "instruction", "model", "api_key", "base_url"):
        assert hidden not in serialized


@pytest.mark.parametrize(
    ("text", "preset"),
    [
        ("请用语音回答头痛怎么办", None),
        ("把刚才的内容读出来", None),
        ("请用粤语回答这个问题", SpeechPreset.CANTONESE),
        ("用上海话给我讲一讲", SpeechPreset.SHANGHAI),
        ("请用男声朗读", SpeechPreset.MANDARIN_MALE),
    ],
)
def test_explicit_speech_intent(text, preset):
    intent = speech_output_request(text)
    assert intent is not None
    assert intent.requested is True
    assert intent.speech_preset == preset


@pytest.mark.parametrize(
    "text",
    [
        "你支持语音输出吗",
        "语音输出功能怎么用",
        "不要用语音，只要文字",
        "比如用户说请用语音回答，应当怎么办",
        "请介绍粤语的历史",
        "什么是朗读障碍",
    ],
)
def test_speech_intent_rejects_inquiries_negation_and_examples(text):
    assert speech_output_request(text) is None


async def test_message_response_exposes_server_speech_intent(profile_context):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    consultation = (
        await client.post(
            "/api/v1/consultations",
            json={"clientRequestId": str(uuid4())},
        )
    ).json()
    response = await client.post(
        f"/api/v1/consultations/{consultation['id']}/messages",
        json={"clientRequestId": str(uuid4()), "content": "请用广东话回答头痛怎么办"},
    )
    assert response.status_code == 201
    assert response.json()["speechOutputIntent"] == {
        "requested": True,
        "speechPreset": "cantonese",
    }


def test_prepare_speech_text_removes_markup_but_keeps_safety_language():
    result = prepare_speech_text(
        """
        ## 就医提示
        - 出现意识不清时请拨打 120。[来源1]
        - 查看[卫健委说明](https://example.test/a)或 https://example.test/b

        ```json
        {"hidden": "不要朗读"}
        ```
        以上仅供健康科普参考，不替代医生面诊。
        """,
        max_chars=4000,
    )
    assert "##" not in result
    assert "来源1" not in result
    assert "http" not in result
    assert "hidden" not in result
    assert "拨打 120" in result
    assert "不替代医生面诊" in result


def test_prepare_speech_text_rejects_empty_and_overlong_content():
    with pytest.raises(AppError) as empty:
        prepare_speech_text("```\nsecret\n```", max_chars=100)
    assert empty.value.code == "SPEECH_MESSAGE_UNSUPPORTED"
    with pytest.raises(AppError) as long:
        prepare_speech_text("需" * 101, max_chars=100)
    assert long.value.code == "SPEECH_TEXT_TOO_LONG"


async def test_speech_endpoint_returns_temporary_mp3_and_audits(
    profile_context, monkeypatch, tmp_path
):
    content = (
        "## 行动建议\n- 先休息。[来源1]\n"
        "- [查看资料](https://example.test/source)\n"
        "以上仅供健康科普参考，不替代医生面诊。"
    )
    client, db, user, _, consultation, _, answer = await _create_answer(
        profile_context,
        content=content,
    )
    captured: dict[str, object] = {}

    async def fake_synthesize(text, *, preset, rate, settings):
        captured.update(text=text, preset=preset, rate=rate, settings=settings)
        return SynthesizedSpeech(b"ID3test-mp3", "local-request-id")

    monkeypatch.setattr(speech, "synthesize_speech", fake_synthesize)
    before = list(tmp_path.iterdir())
    response = await client.post(
        f"/api/v1/consultations/{consultation['id']}/messages/{answer.id}/speech",
        json={"speechPreset": "mandarin_female", "rate": 1.2},
    )
    assert response.status_code == 200
    assert response.content == b"ID3test-mp3"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-speech-preset"] == "mandarin_female"
    assert response.headers["x-request-id"] == "local-request-id"
    assert "http" not in str(captured["text"])
    assert "来源1" not in str(captured["text"])
    assert "不替代医生面诊" in str(captured["text"])
    assert captured["preset"] == SpeechPreset.MANDARIN_FEMALE
    assert captured["rate"] == 1.2
    assert list(tmp_path.iterdir()) == before

    event = await db.scalar(
        select(AuditLog).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action == "synthesize",
            AuditLog.resource_id == answer.id,
        )
    )
    assert event is not None
    assert event.resource_type == "voice_output"
    assert event.outcome == "success"
    assert event.reason_code is None
    assert not hasattr(event, "text")
    assert not hasattr(event, "audio")


async def test_speech_endpoint_enforces_role_status_owner_and_preset(
    profile_context, monkeypatch
):
    client, _, user, other_user, consultation, user_message, answer = await _create_answer(
        profile_context
    )

    async def should_not_run(*_args, **_kwargs):
        raise AssertionError("provider should not run")

    monkeypatch.setattr(speech, "synthesize_speech", should_not_run)
    base = f"/api/v1/consultations/{consultation['id']}/messages"
    user_result = await client.post(
        f"{base}/{user_message['id']}/speech",
        json={"speechPreset": "mandarin_female"},
    )
    assert user_result.status_code == 422
    assert user_result.json()["code"] == "SPEECH_MESSAGE_UNSUPPORTED"

    invalid_preset = await client.post(
        f"{base}/{answer.id}/speech",
        json={"speechPreset": "arbitrary-provider-voice"},
    )
    assert invalid_preset.status_code == 422
    assert invalid_preset.json()["code"] == "SPEECH_PRESET_UNSUPPORTED"

    client.cookies.set(ACCESS_COOKIE, create_access_token(other_user.id))
    cross_user = await client.post(
        f"{base}/{answer.id}/speech",
        json={"speechPreset": "mandarin_female"},
    )
    assert cross_user.status_code == 404
    assert cross_user.json()["code"] == "SPEECH_MESSAGE_NOT_FOUND"
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))

    _, _, _, _, second_consultation, _, stopped = await _create_answer(
        profile_context,
        generation_status="stopped",
    )
    not_ready = await client.post(
        f"/api/v1/consultations/{second_consultation['id']}/messages/{stopped.id}/speech",
        json={"speechPreset": "mandarin_female"},
    )
    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "SPEECH_MESSAGE_NOT_READY"


async def test_speech_provider_failure_is_controlled_and_audited(
    profile_context, monkeypatch
):
    client, db, user, _, consultation, _, answer = await _create_answer(profile_context)

    async def fail(*_args, **_kwargs):
        raise AppError(504, "SPEECH_SERVICE_TIMEOUT", "语音生成超时，请稍后再试")

    monkeypatch.setattr(speech, "synthesize_speech", fail)
    response = await client.post(
        f"/api/v1/consultations/{consultation['id']}/messages/{answer.id}/speech",
        json={"speechPreset": "mandarin_female"},
    )
    assert response.status_code == 504
    assert response.json() == {
        "code": "SPEECH_SERVICE_TIMEOUT",
        "message": "语音生成超时，请稍后再试",
        "details": None,
    }
    event = await db.scalar(
        select(AuditLog).where(
            AuditLog.actor_user_id == user.id,
            AuditLog.resource_id == answer.id,
        )
    )
    assert event is not None
    assert event.outcome == "rejected"
    assert event.reason_code == "SPEECH_SERVICE_TIMEOUT"


async def test_speech_rate_limit_uses_database_audit(profile_context, monkeypatch):
    client, _, _, _, consultation, _, answer = await _create_answer(profile_context)
    settings = get_settings().model_copy(update={"tts_limit_10m": 1, "tts_limit_daily": 1})
    monkeypatch.setattr(speech, "get_settings", lambda: settings)
    monkeypatch.setattr("app.services.speech_limits.get_settings", lambda: settings)

    async def fake_synthesize(*_args, **_kwargs):
        return SynthesizedSpeech(b"ID3test-mp3", "request-id")

    monkeypatch.setattr(speech, "synthesize_speech", fake_synthesize)
    url = f"/api/v1/consultations/{consultation['id']}/messages/{answer.id}/speech"
    assert (
        await client.post(url, json={"speechPreset": "mandarin_female"})
    ).status_code == 200
    limited = await client.post(url, json={"speechPreset": "mandarin_female"})
    assert limited.status_code == 429
    assert limited.json()["code"] == "SPEECH_RATE_LIMITED"


async def test_qwen_tts_uses_server_key_whitelist_and_validates_mp3(monkeypatch):
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured["authorization"] = request.headers.get("authorization")
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                request=request,
                json={
                    "output": {
                        "finish_reason": "stop",
                        "audio": {
                            "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.mp3?sig=x"
                        },
                    }
                },
            )
        captured["download_url"] = str(request.url)
        return httpx.Response(
            200,
            request=request,
            content=b"ID3provider-mp3",
            headers={"Content-Type": "audio/mpeg"},
        )

    async def safe_url(url: str) -> str:
        assert url.startswith("http://dashscope-result-bj.")
        return url.replace("http://", "https://", 1)

    monkeypatch.setattr(
        "app.services.speech_synthesis.validate_audio_url",
        safe_url,
    )
    settings = get_settings().model_copy(
        update={
            "tts_api_key": None,
            "qwen_api_key": SecretStr("server-qwen-key"),
            "tts_base_url": "https://dashscope.aliyuncs.com/api/v1",
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await synthesize_speech(
            "请先休息。",
            preset=SpeechPreset.CANTONESE,
            rate=1.0,
            settings=settings,
            client=client,
        )
    assert result.content == b"ID3provider-mp3"
    assert captured["authorization"] == "Bearer server-qwen-key"
    assert captured["url"] == (
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
    )
    assert str(captured["download_url"]).startswith("https://")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen-audio-3.1-tts-flash"
    assert body["input"]["voice"] == "longanhuan_v3.1"
    assert body["input"]["instruction"] == "请用广东话自然、清晰地表达"
    assert body["input"]["enable_aigc_tag"] is True
    assert "server-qwen-key" not in json.dumps(body)


async def test_qwen_tts_rejects_timeout_invalid_url_and_invalid_audio(monkeypatch):
    settings = get_settings().model_copy(update={"tts_api_key": SecretStr("tts-key")})

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream details", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(AppError) as raised:
            await synthesize_speech(
                "测试",
                preset=SpeechPreset.MANDARIN_FEMALE,
                rate=1.0,
                settings=settings,
                client=client,
            )
    assert raised.value.code == "SPEECH_SERVICE_TIMEOUT"
    assert "details" not in raised.value.message

    calls = 0

    async def invalid(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                request=request,
                json={
                    "output": {
                        "finish_reason": "stop",
                        "audio": {"url": "https://evil.example/audio.mp3"},
                    }
                },
            )
        return httpx.Response(200, request=request, content=b"not-mp3")

    async with httpx.AsyncClient(transport=httpx.MockTransport(invalid)) as client:
        with pytest.raises(AppError) as unsafe:
            await synthesize_speech(
                "测试",
                preset=SpeechPreset.MANDARIN_FEMALE,
                rate=1.0,
                settings=settings,
                client=client,
            )
    assert unsafe.value.code == "SPEECH_SERVICE_UNAVAILABLE"

    async def safe_url(_url: str) -> str:
        return "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.mp3"

    monkeypatch.setattr(
        "app.services.speech_synthesis.validate_audio_url",
        safe_url,
    )
    calls = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(invalid)) as client:
        with pytest.raises(AppError) as invalid_mp3:
            await synthesize_speech(
                "测试",
                preset=SpeechPreset.MANDARIN_FEMALE,
                rate=1.0,
                settings=settings,
                client=client,
            )
    assert invalid_mp3.value.code == "SPEECH_SERVICE_UNAVAILABLE"


async def test_tts_result_url_is_restricted_to_public_beijing_oss(monkeypatch):
    monkeypatch.setattr(
        "app.services.speech_synthesis._public_addresses",
        lambda _hostname: ["8.8.8.8"],
    )
    secured = await validate_audio_url(
        "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.mp3?signature=x"
    )
    assert secured == (
        "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.mp3?signature=x"
    )

    monkeypatch.setattr(
        "app.services.speech_synthesis._public_addresses",
        lambda _hostname: ["127.0.0.1"],
    )
    with pytest.raises(AppError) as private:
        await validate_audio_url(
            "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.mp3"
        )
    assert private.value.code == "SPEECH_SERVICE_UNAVAILABLE"


def test_tts_configuration_rejects_non_beijing_or_compatible_endpoints():
    settings = get_settings()
    for invalid in (
        "http://dashscope.aliyuncs.com/api/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope-intl.aliyuncs.com/api/v1",
        "https://example.com/api/v1",
    ):
        with pytest.raises(ValidationError):
            type(settings).model_validate({**settings.model_dump(), "tts_base_url": invalid})
