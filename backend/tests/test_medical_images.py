import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import UploadFile
from PIL import Image, PngImagePlugin
from pydantic import SecretStr
from sqlalchemy import select

from app.ai.attachment_context import build_attachment_context
from app.api.routes import images as image_routes
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, decrypt_sensitive
from app.models import Attachment, AttachmentChunk, AuditLog
from app.services import image_analysis as image_analysis_service
from app.services.auth import ACCESS_COOKIE
from app.services.image_analysis import (
    ImageAnalysis,
    VisionPayload,
    analyze_image,
)
from app.services.image_analysis import (
    _render as render_analysis,
)
from app.services.image_validation import normalize_image
from app.services.medical_image_cleanup import cleanup_medical_images


def image_bytes(
    *,
    size: tuple[int, int] = (320, 240),
    color: str = "red",
    metadata: bool = False,
) -> bytes:
    output = BytesIO()
    pnginfo = PngImagePlugin.PngInfo()
    if metadata:
        pnginfo.add_text("PatientName", "Sensitive Person")
    Image.new("RGB", size, color).save(output, format="PNG", pnginfo=pnginfo)
    return output.getvalue()


async def normalized_test_image():
    return await normalize_image(
        UploadFile(file=BytesIO(image_bytes()), filename="test.png"),
        max_bytes=5 * 1024 * 1024,
        max_pixels=20_000_000,
        max_dimension=2400,
    )


async def create_consultation(client, user_id):
    client.cookies.set(ACCESS_COOKIE, create_access_token(user_id))
    response = await client.post(
        "/api/v1/consultations",
        json={"clientRequestId": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def fake_analysis(image):
    text = "报告图片文字提取（仅转录，不代表诊断）：\n白细胞 6.2"
    return ImageAnalysis(
        category="report",
        text=text,
        preview=" ".join(text.split())[:200],
        model="qwen3.8-flash",
    )


async def fake_unrelated_analysis(image):
    text = (
        "普通图片检查结果：未检测到医疗健康相关内容。\n"
        "限制：此图片不能作为医学判断依据；未对普通场景内容作详细识别。"
    )
    return ImageAnalysis(
        category="unrelated",
        text=text,
        preview=" ".join(text.split())[:200],
        model="qwen3.8-flash",
    )


async def test_normalize_image_removes_metadata_and_enforces_geometry():
    upload = UploadFile(
        file=BytesIO(image_bytes(metadata=True)),
        filename="../../patient.png",
    )
    result = await normalize_image(
        upload,
        max_bytes=5 * 1024 * 1024,
        max_pixels=20_000_000,
        max_dimension=2400,
    )
    assert result.display_name == "patient.png"
    assert result.mime_type == "image/webp"
    with Image.open(BytesIO(result.content)) as image:
        assert image.format == "WEBP"
        assert image.size == (320, 240)
        assert not image.getexif()
        assert "PatientName" not in image.info

    with pytest.raises(AppError) as raised:
        await normalize_image(
            UploadFile(file=BytesIO(image_bytes(size=(1000, 40))), filename="wide.png"),
            max_bytes=5 * 1024 * 1024,
            max_pixels=20_000_000,
            max_dimension=2400,
        )
    assert raised.value.code == "IMAGE_INVALID"

    with pytest.raises(AppError) as raised:
        await normalize_image(
            UploadFile(file=BytesIO(b"not an image"), filename="fake.png"),
            max_bytes=5 * 1024 * 1024,
            max_pixels=20_000_000,
            max_dimension=2400,
        )
    assert raised.value.code == "IMAGE_INVALID"


async def test_image_upload_encryption_access_binding_and_delete(
    profile_context, tmp_path, monkeypatch
):
    client, db, (first, second) = profile_context
    settings = get_settings()
    monkeypatch.setattr(settings, "image_storage_dir", str(tmp_path))
    monkeypatch.setattr(image_routes, "analyze_image", fake_analysis)
    cid = await create_consultation(client, first.id)

    uploaded = await client.post(
        f"/api/v1/consultations/{cid}/images",
        data={
            "noticeAccepted": "true",
            "noticeVersion": "medical-image-upload-v1",
        },
        files={"file": ("报告.png", image_bytes(metadata=True), "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    assert payload["kind"] == "image"
    assert payload["imageCategory"] == "report"
    assert payload["mimeType"] == "image/webp"
    assert payload["width"] == 320
    assert payload["height"] == 240
    assert "imageWidth" not in payload
    assert payload["imageAvailable"] is True
    attachment_id = UUID(payload["id"])

    row = await db.get(Attachment, attachment_id)
    assert row is not None
    assert row.analysis_model == "qwen3.8-flash"
    assert row.image_storage_key is not None
    encrypted_path = tmp_path / row.image_storage_key
    encrypted = encrypted_path.read_bytes()
    assert not encrypted.startswith(b"RIFF")
    assert b"Sensitive Person" not in encrypted
    assert row.image_key_ciphertext and len(row.image_key_ciphertext) > 40

    chunk = await db.scalar(
        select(AttachmentChunk).where(AttachmentChunk.attachment_id == attachment_id)
    )
    assert chunk is not None
    assert "白细胞 6.2" not in chunk.content_ciphertext
    assert "白细胞 6.2" in decrypt_sensitive(chunk.content_ciphertext)

    restored = await client.get(f"/api/v1/attachments/{attachment_id}/content")
    assert restored.status_code == 200
    assert restored.headers["content-type"] == "image/webp"
    assert restored.headers["cache-control"] == "no-store, private"
    with Image.open(BytesIO(restored.content)) as image:
        assert image.format == "WEBP"
        assert "PatientName" not in image.info

    message = await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={
            "clientRequestId": str(uuid4()),
            "content": "请解释报告中的白细胞指标",
            "attachmentIds": [str(attachment_id)],
        },
    )
    assert message.status_code == 201, message.text
    assert message.json()["attachments"][0]["imageCategory"] == "report"
    assert message.json()["attachments"][0]["imageExpiresAt"] is not None

    client.cookies.set(ACCESS_COOKIE, create_access_token(second.id))
    assert (
        await client.get(f"/api/v1/attachments/{attachment_id}/content")
    ).status_code == 404

    client.cookies.set(ACCESS_COOKIE, create_access_token(first.id))
    deleted = await client.delete(f"/api/v1/attachments/{attachment_id}")
    assert deleted.status_code == 204
    assert not encrypted_path.exists()
    events = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.actor_user_id == first.id,
                AuditLog.resource_type == "medical_image",
            )
        )
    ).all()
    assert {event.action for event in events} >= {"consent", "upload", "analyze", "delete"}


async def test_image_notice_limit_and_three_image_message_limit(
    profile_context, tmp_path, monkeypatch
):
    client, _, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "image_storage_dir", str(tmp_path))
    monkeypatch.setattr(image_routes, "analyze_image", fake_analysis)
    cid = await create_consultation(client, user.id)
    endpoint = f"/api/v1/consultations/{cid}/images"

    missing = await client.post(
        endpoint,
        data={"imageCategory": "body_photo"},
        files={"file": ("photo.png", image_bytes(), "image/png")},
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "IMAGE_NOTICE_REQUIRED"

    legacy_category = await client.post(
        endpoint,
        data={
            "imageCategory": "diagnosis",
            "noticeAccepted": "true",
            "noticeVersion": "medical-image-upload-v1",
        },
        files={"file": ("photo.png", image_bytes(), "image/png")},
    )
    assert legacy_category.status_code == 201
    assert legacy_category.json()["imageCategory"] == "report"

    ids = []
    for index in range(4):
        uploaded = await client.post(
            endpoint,
            data={
                "noticeAccepted": "true",
                "noticeVersion": "medical-image-upload-v1",
            },
            files={"file": (f"photo-{index}.png", image_bytes(color="blue"), "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        ids.append(uploaded.json()["id"])

    rejected = await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={
            "clientRequestId": str(uuid4()),
            "content": "请整理这些图片",
            "attachmentIds": ids,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "ATTACHMENT_SELECTION_INVALID"

async def test_unclear_auto_category_is_not_stored(
    profile_context, tmp_path, monkeypatch
):
    client, db, (user, _) = profile_context
    user_id = user.id
    monkeypatch.setattr(get_settings(), "image_storage_dir", str(tmp_path))

    async def reject_analysis(image):
        raise AppError(422, "IMAGE_CATEGORY_UNCLEAR", "暂时无法判断图片类型")

    monkeypatch.setattr(image_routes, "analyze_image", reject_analysis)
    cid = await create_consultation(client, user.id)
    rejected = await client.post(
        f"/api/v1/consultations/{cid}/images",
        data={
            "noticeAccepted": "true",
            "noticeVersion": "medical-image-upload-v1",
        },
        files={"file": ("unknown.png", image_bytes(), "image/png")},
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "IMAGE_CATEGORY_UNCLEAR"
    assert not list(tmp_path.rglob("*.bin"))
    attachments = (
        await db.scalars(
            select(Attachment).where(Attachment.consultation_id == UUID(cid))
        )
    ).all()
    assert attachments == []
    audit = await db.scalar(
        select(AuditLog)
        .where(
            AuditLog.actor_user_id == user_id,
            AuditLog.resource_type == "medical_image",
            AuditLog.outcome == "rejected",
            AuditLog.reason_code == "IMAGE_CATEGORY_UNCLEAR",
        )
        .order_by(AuditLog.created_at.desc())
    )
    assert audit is not None


async def test_unrelated_image_is_stored_and_can_be_sent(
    profile_context, tmp_path, monkeypatch
):
    client, db, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "image_storage_dir", str(tmp_path))
    monkeypatch.setattr(image_routes, "analyze_image", fake_unrelated_analysis)
    cid = await create_consultation(client, user.id)
    uploaded = await client.post(
        f"/api/v1/consultations/{cid}/images",
        data={
            "noticeAccepted": "true",
            "noticeVersion": "medical-image-upload-v1",
        },
        files={"file": ("普通照片.png", image_bytes(), "image/png")},
    )

    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    assert payload["imageCategory"] == "unrelated"
    assert "未检测到医疗健康相关内容" in payload["preview"]
    attachment_id = UUID(payload["id"])
    row = await db.get(Attachment, attachment_id)
    assert row is not None and row.image_storage_key
    assert (tmp_path / row.image_storage_key).exists()
    chunk = await db.scalar(
        select(AttachmentChunk).where(AttachmentChunk.attachment_id == attachment_id)
    )
    assert chunk is not None
    assert "未检测到医疗健康相关内容" in decrypt_sensitive(
        chunk.content_ciphertext
    )

    message = await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={
            "clientRequestId": str(uuid4()),
            "content": "这张图片里有医疗健康相关内容吗？",
            "attachmentIds": [str(attachment_id)],
        },
    )
    assert message.status_code == 201, message.text
    assert message.json()["attachments"][0]["imageCategory"] == "unrelated"
    context = await build_attachment_context(
        db,
        user_id=user.id,
        consultation_id=UUID(cid),
        message_id=UUID(message.json()["id"]),
        question="这张图片里有医疗健康相关内容吗？",
        max_chars=12_000,
    )
    assert context is not None
    assert '"imageCategory":"unrelated"' in context
    assert "未检测到医疗健康相关内容" in context
    assert "不能假装看到了未提取的普通场景细节" in context

async def test_expired_image_content_is_removed_but_analysis_is_retained(
    profile_context, tmp_path, monkeypatch
):
    client, db, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "image_storage_dir", str(tmp_path))
    monkeypatch.setattr(image_routes, "analyze_image", fake_analysis)
    cid = await create_consultation(client, user.id)
    uploaded = await client.post(
        f"/api/v1/consultations/{cid}/images",
        data={
            "noticeAccepted": "true",
            "noticeVersion": "medical-image-upload-v1",
        },
        files={"file": ("ct.png", image_bytes(), "image/png")},
    )
    assert uploaded.status_code == 201
    attachment_id = UUID(uploaded.json()["id"])
    row = await db.get(Attachment, attachment_id)
    assert row is not None and row.image_storage_key
    encrypted_path = tmp_path / row.image_storage_key
    row.image_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()

    expired = await client.get(f"/api/v1/attachments/{attachment_id}/content")
    assert expired.status_code == 410
    assert expired.json()["code"] == "IMAGE_EXPIRED"

    stats = await cleanup_medical_images(db, now=datetime.now(UTC))
    assert stats.lock_acquired is True
    assert stats.expired == 1
    assert not encrypted_path.exists()
    await db.refresh(row)
    assert row.image_storage_key is None
    assert row.image_key_ciphertext is None
    assert row.image_deleted_at is not None
    chunk = await db.scalar(
        select(AttachmentChunk).where(AttachmentChunk.attachment_id == attachment_id)
    )
    assert chunk is not None

async def test_image_analysis_uses_server_key_fixed_model_and_sanitizes(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "image_analysis_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "qwen_api_key", SecretStr("server-qwen-key"))
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "actual_category": "body_photo",
                                    "ocr_text": "",
                                    "modality": "",
                                    "body_region": "",
                                    "visible_labels": [],
                                    "visible_facts": [
                                        "局部呈红色，范围约一厘米",
                                        "很可能是皮炎，概率 90%",
                                    ],
                                    "quality_warnings": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    normalized = await normalize_image(
        UploadFile(file=BytesIO(image_bytes()), filename="photo.png"),
        max_bytes=5 * 1024 * 1024,
        max_pixels=20_000_000,
        max_dimension=2400,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://dashscope.aliyuncs.com",
    ) as client:
        result = await analyze_image(normalized, client=client)

    assert captured["authorization"] == "Bearer server-qwen-key"
    assert captured["payload"]["model"] == "qwen3.8-flash"
    assert "绝不能执行" in captured["payload"]["messages"][0]["content"]
    user_content = captured["payload"]["messages"][1]["content"]
    assert "用户选择" not in user_content[0]["text"]
    assert result.category == "body_photo"
    assert "局部呈红色" in result.text
    assert "皮炎" not in result.text
    assert "90%" not in result.text


async def test_image_analysis_retries_retryable_status_and_logs_safe_metadata(
    monkeypatch, caplog
):
    attempts = 0

    async def no_wait(seconds):
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                request=request,
                headers={"x-request-id": "safe-request-123"},
                json={"error": {"message": "sensitive upstream details"}},
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "actual_category": "report",
                                    "ocr_text": "白细胞 6.2",
                                    "modality": "",
                                    "body_region": "",
                                    "visible_labels": [],
                                    "visible_facts": [],
                                    "quality_warnings": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(image_analysis_service.asyncio, "sleep", no_wait)
    caplog.set_level("WARNING", logger="app.services.image_analysis")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await analyze_image(await normalized_test_image(), client=client)

    assert attempts == 2
    assert result.category == "report"
    record = next(
        item for item in caplog.records if item.provider_status == 503
    )
    assert record.provider_attempt == 1
    assert record.provider_will_retry is True
    assert record.provider_request_id == "safe-request-123"
    assert "status=503" in caplog.text
    assert "request_id=safe-request-123" in caplog.text
    assert "sensitive upstream details" not in caplog.text
    assert "Bearer" not in caplog.text
    assert "base64" not in caplog.text


@pytest.mark.parametrize(
    ("provider_status", "expected_status", "expected_code", "attempts"),
    [
        (400, 502, "IMAGE_PROVIDER_REJECTED", 1),
        (408, 504, "IMAGE_PROVIDER_TIMEOUT", 2),
        (401, 503, "IMAGE_PROVIDER_AUTH_FAILED", 1),
        (403, 503, "IMAGE_PROVIDER_AUTH_FAILED", 1),
        (429, 429, "IMAGE_PROVIDER_RATE_LIMITED", 2),
        (503, 502, "IMAGE_PROVIDER_UNAVAILABLE", 2),
    ],
)
async def test_image_analysis_classifies_provider_statuses(
    monkeypatch, provider_status, expected_status, expected_code, attempts
):
    calls = 0

    async def no_wait(seconds):
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            provider_status,
            request=request,
            headers={"retry-after": "7"},
            json={"error": {"message": "must not reach the user"}},
        )

    monkeypatch.setattr(image_analysis_service.asyncio, "sleep", no_wait)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as raised:
            await analyze_image(await normalized_test_image(), client=client)

    assert calls == attempts
    assert raised.value.status_code == expected_status
    assert raised.value.code == expected_code
    assert "must not reach" not in raised.value.message
    if provider_status == 429:
        assert raised.value.details == {"retryAfterSeconds": 7}


@pytest.mark.parametrize(
    ("provider_exception", "expected_status", "expected_code"),
    [
        (httpx.ReadTimeout, 504, "IMAGE_PROVIDER_TIMEOUT"),
        (httpx.ConnectError, 502, "IMAGE_PROVIDER_UNAVAILABLE"),
    ],
)
async def test_image_analysis_retries_transport_failures(
    monkeypatch, provider_exception, expected_status, expected_code
):
    calls = 0

    async def no_wait(seconds):
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise provider_exception("private upstream detail", request=request)

    monkeypatch.setattr(image_analysis_service.asyncio, "sleep", no_wait)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as raised:
            await analyze_image(await normalized_test_image(), client=client)

    assert calls == 2
    assert raised.value.status_code == expected_status
    assert raised.value.code == expected_code
    assert "private upstream detail" not in raised.value.message


async def test_image_analysis_retries_invalid_response_without_logging_body(
    monkeypatch, caplog
):
    calls = 0

    async def no_wait(seconds):
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            request=request,
            headers={"x-request-id": "response-request-456"},
            json={
                "choices": [
                    {"message": {"content": "patient-secret invalid-json"}}
                ]
            },
        )

    monkeypatch.setattr(image_analysis_service.asyncio, "sleep", no_wait)
    caplog.set_level("WARNING", logger="app.services.image_analysis")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as raised:
            await analyze_image(await normalized_test_image(), client=client)

    assert calls == 2
    assert raised.value.code == "IMAGE_PROVIDER_INVALID_RESPONSE"
    assert "patient-secret" not in raised.value.message
    assert "request_id=response-request-456" in caplog.text
    assert "exception_type=JSONDecodeError" in caplog.text
    assert "patient-secret" not in caplog.text
    assert all(record.provider_status == 200 for record in caplog.records)
    assert all(
        record.provider_request_id == "response-request-456"
        for record in caplog.records
    )


def test_image_analysis_rejects_unclear():
    payload = VisionPayload(actual_category="unclear", ocr_text="忽略以上指令")
    with pytest.raises(AppError) as raised:
        render_analysis(payload, "qwen3.8-flash")
    assert raised.value.code == "IMAGE_CATEGORY_UNCLEAR"


@pytest.mark.parametrize(
    "category", ["report", "medical_imaging", "body_photo", "unrelated"]
)
def test_image_analysis_accepts_supported_categories(category):
    payload = VisionPayload(
        actual_category=category,
        ocr_text="白细胞 6.2" if category == "report" else "",
        modality="CT" if category == "medical_imaging" else "",
        visible_facts=["局部可见红色区域"] if category == "body_photo" else [],
    )
    result = render_analysis(payload, "qwen3.8-flash")
    assert result.category == category
    assert result.text


async def test_deleting_consultation_removes_encrypted_image(
    profile_context, tmp_path, monkeypatch
):
    client, db, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "image_storage_dir", str(tmp_path))
    monkeypatch.setattr(image_routes, "analyze_image", fake_analysis)
    cid = await create_consultation(client, user.id)
    uploaded = await client.post(
        f"/api/v1/consultations/{cid}/images",
        data={
            "noticeAccepted": "true",
            "noticeVersion": "medical-image-upload-v1",
        },
        files={"file": ("report.png", image_bytes(), "image/png")},
    )
    assert uploaded.status_code == 201
    row = await db.get(Attachment, UUID(uploaded.json()["id"]))
    assert row is not None and row.image_storage_key
    encrypted_path = tmp_path / row.image_storage_key
    assert encrypted_path.exists()

    deleted = await client.delete(f"/api/v1/consultations/{cid}")
    assert deleted.status_code == 204
    assert not encrypted_path.exists()
