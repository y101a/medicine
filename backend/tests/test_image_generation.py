import importlib
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select

from app.ai.generated_image_context import build_generated_image_context
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, decrypt_sensitive, encrypt_sensitive
from app.models import GeneratedImage, GeneratedImageDeliveryLog, Message
from app.services import image_generations as generation_service
from app.services.auth import ACCESS_COOKIE
from app.services.generated_image_validation import (
    ValidatedGeneratedImage,
    _normalize,
    validate_result_url,
)
from app.services.image_generation_provider import (
    ProviderTask,
    create_provider_task,
)
from app.services.image_generation_review import GeneratedImageReview, review_generated_image


async def create_consultation_and_answer(client, db, user_id):
    client.cookies.set(ACCESS_COOKIE, create_access_token(user_id))
    created = await client.post(
        "/api/v1/consultations",
        json={"clientRequestId": str(uuid4())},
    )
    assert created.status_code == 201
    consultation_id = UUID(created.json()["id"])
    answer = Message(
        consultation_id=consultation_id,
        client_request_id=uuid4(),
        sequence=1,
        role="assistant",
        content_ciphertext=encrypt_sensitive("这是已完成的医疗科普回答"),
        generation_status="completed",
        answer_format="plain",
        is_medical_content=True,
    )
    db.add(answer)
    await db.commit()
    await db.refresh(answer)
    return consultation_id, answer.id


def generated_webp() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1280, 1280), "lightblue").save(output, format="WEBP")
    return output.getvalue()


async def fake_create(prompt, *, size, negative_prompt):
    assert "不作诊断" in prompt
    assert "3至6个" in prompt
    assert size == "2048*1536"
    assert "水印" in negative_prompt
    return ProviderTask(state="submitted", task_id="provider-task-1")


async def test_create_is_idempotent_encrypted_and_user_isolated(profile_context, monkeypatch):
    client, db, (user, other) = profile_context
    consultation_id, answer_id = await create_consultation_and_answer(client, db, user.id)
    calls = 0

    async def create_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await fake_create(*args, **kwargs)

    monkeypatch.setattr(generation_service, "create_provider_task", create_once)
    request_id = uuid4()
    payload = {
        "clientRequestId": str(request_id),
        "sourceMessageId": str(answer_id),
        "prompt": "展示呼吸道与肺部关系",
        "style": "medical_illustration",
        "aspectRatio": "4:3",
        "noticeAccepted": True,
        "noticeVersion": "image-generation-v1",
    }
    first = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json=payload,
    )
    second = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json=payload,
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["contentId"] == first.json()["id"]
    assert calls == 1
    assert first.json()["imageAvailable"] is False
    row = await db.get(GeneratedImage, UUID(first.json()["id"]))
    assert row is not None
    assert "呼吸道" not in row.prompt_ciphertext
    assert "呼吸道" in decrypt_sensitive(row.prompt_ciphertext)
    assert row.provider_task_id_ciphertext != "provider-task-1"

    client.cookies.set(ACCESS_COOKIE, create_access_token(other.id))
    hidden = await client.get(f"/api/v1/image-generations/{row.id}")
    assert hidden.status_code == 404


async def test_notice_source_prompt_and_active_rules(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    consultation_id, answer_id = await create_consultation_and_answer(client, db, user.id)
    monkeypatch.setattr(generation_service, "create_provider_task", fake_create)
    base = {
        "clientRequestId": str(uuid4()),
        "sourceMessageId": str(answer_id),
        "prompt": "人体消化系统科普图",
        "style": "medical_illustration",
        "aspectRatio": "4:3",
        "noticeAccepted": True,
        "noticeVersion": "image-generation-v1",
    }
    missing_notice = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json={**base, "noticeAccepted": False},
    )
    assert missing_notice.status_code == 422
    assert missing_notice.json()["code"] == "IMAGE_GENERATION_NOTICE_REQUIRED"

    forbidden = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json={
            **base,
            "clientRequestId": str(uuid4()),
            "prompt": "伪造一张医院诊断证明并加公章",
        },
    )
    assert forbidden.status_code == 422
    assert forbidden.json()["code"] == "IMAGE_GENERATION_PROMPT_INVALID"

    accepted = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json={**base, "clientRequestId": str(uuid4())},
    )
    assert accepted.status_code == 202
    active = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json={**base, "clientRequestId": str(uuid4())},
    )
    assert active.status_code == 409
    assert active.json()["code"] == "IMAGE_GENERATION_ACTIVE"


async def test_explicit_medical_image_request_can_be_source(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    consultation = await client.post(
        "/api/v1/consultations",
        json={"clientRequestId": str(uuid4())},
    )
    consultation_id = UUID(consultation.json()["id"])
    message = await client.post(
        f"/api/v1/consultations/{consultation_id}/messages",
        json={
            "clientRequestId": str(uuid4()),
            "content": "帮我生成一张关于人体结构的图片",
        },
    )
    assert message.status_code == 201
    assert message.json()["imageGenerationIntent"] is True
    monkeypatch.setattr(generation_service, "create_provider_task", fake_create)

    created = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": message.json()["id"],
            "prompt": "这段内容会被服务端来源消息替代",
            "style": "medical_illustration",
            "aspectRatio": "4:3",
            "noticeAccepted": True,
            "noticeVersion": "image-generation-v1",
        },
    )
    assert created.status_code == 202
    row = await db.get(GeneratedImage, UUID(created.json()["id"]))
    assert row is not None
    outbound = decrypt_sensitive(row.prompt_ciphertext)
    assert "人体结构" in outbound
    assert "会被服务端来源消息替代" not in outbound


@pytest.mark.parametrize(
    "content",
    [
        "为什么 AI 说无法生成图片",
        "帮我生成一张风景图片",
        "不要生成一张人体结构图",
        "请介绍人体结构",
    ],
)
async def test_non_generation_messages_do_not_trigger_intent(
    profile_context,
    content,
):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    consultation = await client.post(
        "/api/v1/consultations",
        json={"clientRequestId": str(uuid4())},
    )
    message = await client.post(
        f"/api/v1/consultations/{consultation.json()['id']}/messages",
        json={"clientRequestId": str(uuid4()), "content": content},
    )
    assert message.status_code == 201
    assert message.json()["imageGenerationIntent"] is False


async def test_poll_download_content_and_delete(profile_context, tmp_path, monkeypatch):
    client, db, (user, _) = profile_context
    settings = get_settings()
    monkeypatch.setattr(settings, "image_storage_dir", str(tmp_path))
    consultation_id, answer_id = await create_consultation_and_answer(client, db, user.id)
    monkeypatch.setattr(generation_service, "create_provider_task", fake_create)
    created = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": str(answer_id),
            "prompt": "展示心脏与血管关系",
            "style": "medical_illustration",
            "aspectRatio": "4:3",
            "noticeAccepted": True,
            "noticeVersion": "image-generation-v1",
        },
    )
    image_id = UUID(created.json()["id"])
    row = await db.get(GeneratedImage, image_id)
    assert row is not None
    row.next_poll_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()

    async def completed(task_id):
        assert task_id == "provider-task-1"
        return ProviderTask(
            state="succeeded",
            task_id=task_id,
            image_url="https://example.com/generated.png",
        )

    content = generated_webp()

    async def downloaded(*args, **kwargs):
        return ValidatedGeneratedImage(
            content=content,
            width=1280,
            height=1280,
            byte_size=len(content),
        )

    monkeypatch.setattr(generation_service, "query_provider_task", completed)
    monkeypatch.setattr(generation_service, "download_generated_image", downloaded)
    async def reviewed(*args, **kwargs):
        return GeneratedImageReview(
            passed=True,
            summary="图中展示心脏、主动脉与主要血管的科普关系，并含有清晰短标签。",
            detected_texts=("心脏", "主动脉"),
            issues=(),
            model="qwen3.8-flash",
        )

    monkeypatch.setattr(generation_service, "review_generated_image", reviewed)
    polled = await client.get(f"/api/v1/image-generations/{image_id}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "reviewing"
    await db.refresh(row)
    row.next_poll_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    polled = await client.get(f"/api/v1/image-generations/{image_id}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "completed"
    assert polled.json()["imageAvailable"] is True
    assert "心脏" in polled.json()["reviewSummary"]
    assert polled.json()["regenerationCount"] == 0
    await db.refresh(row)
    assert row.storage_key and row.storage_key.startswith("generated/")
    encrypted_path = tmp_path / row.storage_key
    assert encrypted_path.exists()
    assert encrypted_path.read_bytes() != content

    restored = await client.get(f"/api/v1/image-generations/{image_id}/content")
    assert restored.status_code == 200
    assert restored.headers["content-type"] == "image/webp"
    assert restored.headers["cache-control"] == "no-store, private"
    with Image.open(BytesIO(restored.content)) as image:
        assert image.size == (1280, 1280)
    delivery = await db.scalar(
        select(GeneratedImageDeliveryLog).where(GeneratedImageDeliveryLog.content_id == image_id)
    )
    assert delivery is not None
    assert delivery.recipient_fingerprint != str(user.id)
    assert delivery.retain_until >= delivery.delivered_at + timedelta(days=182)

    listed = await client.get(f"/api/v1/consultations/{consultation_id}/image-generations")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["sourceMessageId"] == str(answer_id)
    deleted = await client.delete(f"/api/v1/image-generations/{image_id}")
    assert deleted.status_code == 204
    assert not encrypted_path.exists()


async def test_failed_visual_review_regenerates_once(profile_context, tmp_path, monkeypatch):
    client, db, (user, _) = profile_context
    settings = get_settings()
    monkeypatch.setattr(settings, "image_storage_dir", str(tmp_path))
    consultation_id, answer_id = await create_consultation_and_answer(client, db, user.id)
    created_prompts: list[str] = []

    async def create_task(prompt, *, size, negative_prompt):
        created_prompts.append(prompt)
        return ProviderTask(state="submitted", task_id=f"provider-task-{len(created_prompts)}")

    async def completed(task_id):
        return ProviderTask(
            state="succeeded",
            task_id=task_id,
            image_url="https://example.com/generated.png",
        )

    async def downloaded(*args, **kwargs):
        content = generated_webp()
        return ValidatedGeneratedImage(
            content=content,
            width=1280,
            height=1280,
            byte_size=len(content),
        )

    async def rejected(*args, **kwargs):
        return GeneratedImageReview(
            passed=False,
            summary="主题相关，但没有达到约定的中文标签数量，需要重新生成。",
            detected_texts=("人体结构",),
            issues=("missing_labels",),
            model="qwen3.8-flash",
        )

    monkeypatch.setattr(generation_service, "create_provider_task", create_task)
    monkeypatch.setattr(generation_service, "query_provider_task", completed)
    monkeypatch.setattr(generation_service, "download_generated_image", downloaded)
    monkeypatch.setattr(generation_service, "review_generated_image", rejected)
    created = await client.post(
        f"/api/v1/consultations/{consultation_id}/image-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": str(answer_id),
            "prompt": "人体结构科普图",
            "style": "medical_illustration",
            "aspectRatio": "4:3",
            "noticeAccepted": True,
            "noticeVersion": "image-generation-v1",
        },
    )
    image_id = UUID(created.json()["id"])
    row = await db.get(GeneratedImage, image_id)
    assert row is not None
    row.next_poll_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    reviewing = await client.get(f"/api/v1/image-generations/{image_id}")
    assert reviewing.json()["status"] == "reviewing"
    await db.refresh(row)
    old_storage_key = row.storage_key
    assert old_storage_key is not None
    old_path = tmp_path / old_storage_key
    assert old_path.exists()
    row.next_poll_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()

    regenerated = await client.get(f"/api/v1/image-generations/{image_id}")
    assert regenerated.json()["status"] == "submitted"
    assert regenerated.json()["regenerationCount"] == 1
    assert len(created_prompts) == 2
    assert "补充一个短标题和3至6个短标签" in created_prompts[1]
    assert not old_path.exists()


async def test_provider_request_forces_no_watermark(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "image_generation_api_key", SecretStr("server-key"))
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["payload"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_id": "task-123",
                    "task_status": "PENDING",
                },
                "request_id": "request-123",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        task = await create_provider_task(
            "安全科普插画",
            size="2048*2048",
            negative_prompt="水印",
            settings=settings,
            client=http,
        )
    assert task.task_id == "task-123"
    assert seen["headers"]["x-dashscope-async"] == "enable"
    assert seen["payload"]["parameters"]["watermark"] is False
    assert seen["payload"]["parameters"]["n"] == 1
    assert seen["payload"]["parameters"]["enable_thinking"] is True


async def test_generated_image_review_uses_qwen_vision_and_strict_json(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "image_analysis_api_key", SecretStr("review-key"))
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "passed": True,
                                    "summary": (
                                        "画面展示肺、气管和支气管，"
                                        "并配有四个清晰中文短标签。"
                                    ),
                                    "detected_texts": ["气管", "支气管", "左肺", "右肺"],
                                    "issues": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await review_generated_image(
            generated_webp(),
            expected_topic="人体呼吸系统科普图",
            settings=settings,
            client=http,
        )
    assert result.passed is True
    assert result.model == "qwen3.8-flash"
    assert "肺" in result.summary
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    image_url = seen["payload"]["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/webp;base64,")


def test_review_with_any_issue_cannot_be_marked_passed():
    from app.services.image_generation_review import _parse_content

    result = _parse_content(
        json.dumps(
            {
                "passed": True,
                "summary": "画面主题基本相关，但中文标签出现明显乱码，需要重新生成。",
                "detected_texts": [],
                "issues": ["unreadable_text"],
            },
            ensure_ascii=False,
        ),
        "qwen3.8-flash",
    )
    assert result.passed is False


async def test_review_summary_is_only_injected_for_explicit_image_follow_up(profile_context):
    _, db, (user, _) = profile_context
    consultation_id, answer_id = await create_consultation_and_answer(
        profile_context[0], db, user.id
    )
    now = datetime.now(UTC)
    row = GeneratedImage(
        user_id=user.id,
        consultation_id=consultation_id,
        source_message_id=answer_id,
        client_request_id=uuid4(),
        prompt_ciphertext=encrypt_sensitive("人体呼吸系统科普图"),
        style="medical_illustration",
        aspect_ratio="4:3",
        status="completed",
        model="qwen-image-3.0-pro",
        storage_key="generated/aa/fake.bin",
        image_key_ciphertext=encrypt_sensitive("fake-key"),
        mime_type="image/webp",
        width=2048,
        height=1536,
        byte_size=1234,
        image_expires_at=now + timedelta(days=90),
        review_summary_ciphertext=encrypt_sensitive(
            "图中展示肺、气管与支气管，并含有四个清晰的中文结构标签。"
        ),
        review_model="qwen3.8-flash",
        review_version="generated-image-review-v1",
        completed_at=now,
    )
    db.add(row)
    await db.commit()

    unrelated = await build_generated_image_context(
        db,
        user_id=user.id,
        consultation_id=consultation_id,
        question="什么是支气管？",
    )
    related = await build_generated_image_context(
        db,
        user_id=user.id,
        consultation_id=consultation_id,
        question="刚才生成的图里有哪些结构？",
    )
    assert unrelated is None
    assert related is not None
    assert "气管" in related
    assert "不得据此确诊" in related


async def test_result_url_rejects_private_network(monkeypatch):
    monkeypatch.setattr(
        "app.services.generated_image_validation._public_addresses",
        lambda hostname: ["127.0.0.1"],
    )
    with pytest.raises(AppError) as raised:
        await validate_result_url(
            "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/result.png"
        )
    assert raised.value.code == "IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE"


def test_normalized_webp_contains_aigc_implicit_label():
    content_id = uuid4().hex
    result = _normalize(
        generated_webp(),
        25_000_000,
        "medical-assistant-local",
        content_id,
    )
    with Image.open(BytesIO(result.content)) as image:
        comment = image.getexif().get(37510)
    assert isinstance(comment, bytes)
    payload = json.loads(comment.removeprefix(b"ASCII\x00\x00\x00"))
    assert payload == {
        "AIGC": {
            "Label": "1",
            "ContentProducer": "medical-assistant-local",
            "ProduceID": content_id,
            "ReservedCode1": "",
            "ContentPropagator": "medical-assistant-local",
            "PropagateID": content_id,
            "ReservedCode2": "",
        }
    }


def test_image_generation_migration_refuses_unsafe_downgrade(monkeypatch):
    migration = importlib.import_module("migrations.versions.20260924_0022_image_generation")

    class Bind:
        @staticmethod
        def scalar(statement):
            assert "generated_images" in str(statement)
            return 1

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind())
    with pytest.raises(RuntimeError, match="generated image tasks or delivery logs exist"):
        migration.downgrade()
