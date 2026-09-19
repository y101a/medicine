"""Health record API tests.

These need PostgreSQL. The router is mounted on a local app so the suite works both
before and after registration in ``app.api.router``.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.ai.health_extract import ExtractedFact
from app.api.routes.health_records import router as health_records_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, decrypt_sensitive, encrypt_sensitive
from app.db.session import get_db
from app.main import handle_app_error, handle_validation_error
from app.models import Consultation, Gender, HealthRecord, HealthRecordCategory, Message, User
from app.services import health_records as service
from app.services.auth import ACCESS_COOKIE

API = "/api/v1/health-records"


@pytest.fixture
async def health_context():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            users = []
            for name in ("健康甲", "健康乙"):
                suffix = uuid4().hex
                user = User(
                    username=suffix[:16],
                    username_normalized=suffix[:16],
                    real_name_ciphertext=encrypt_sensitive(name),
                    phone_ciphertext=encrypt_sensitive("13800138000"),
                    phone_fingerprint=suffix,
                    id_card_ciphertext=encrypt_sensitive("11010519491231002X"),
                    id_card_fingerprint=suffix,
                    gender=Gender.PRIVATE,
                )
                db.add(user)
                users.append(user)
            await db.flush()

            test_app = FastAPI()
            test_app.add_exception_handler(AppError, handle_app_error)
            test_app.add_exception_handler(RequestValidationError, handle_validation_error)
            test_app.include_router(health_records_router, prefix="/api/v1")

            async def override_db():
                yield db

            test_app.dependency_overrides[get_db] = override_db
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=test_app), base_url="http://test"
                ) as client:
                    yield client, db, users
            finally:
                test_app.dependency_overrides.pop(get_db, None)
        await transaction.rollback()
    await engine.dispose()


def authenticate(client: AsyncClient, user: User) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))


async def add_exchange(
    db: AsyncSession, user: User, text: str, *, medical: bool = True
) -> tuple[Message, Message]:
    """建立一次真实形态的问答：用户消息不带标记，助手回答带。

    线上只有助手构造器会写 ``is_medical_content``（见 ``app/services/consultations.py``），
    用户消息始终是模型默认的 False。旧版辅助函数直接给**用户**消息置 True，那是线上造不出来
    的状态，因此提取链路实际不生效却一直有测试通过。
    """
    consultation = Consultation(
        user_id=user.id,
        client_request_id=uuid4(),
        title_ciphertext=encrypt_sensitive("测试会话"),
    )
    db.add(consultation)
    await db.flush()
    question = Message(
        consultation_id=consultation.id,
        client_request_id=uuid4(),
        sequence=1,
        role="user",
        content_ciphertext=encrypt_sensitive(text),
    )
    answer = Message(
        consultation_id=consultation.id,
        client_request_id=uuid4(),
        sequence=2,
        role="assistant",
        content_ciphertext=encrypt_sensitive("测试回答"),
        is_medical_content=medical,
    )
    db.add_all([question, answer])
    await db.flush()
    return question, answer


async def test_settings_default_to_collecting_before_first_notice(health_context):
    client, _, (user, _) = health_context
    assert (await client.get(f"{API}/settings")).status_code == 401
    authenticate(client, user)
    assert (await client.get(f"{API}/settings")).json() == {
        "collectionEnabled": True,
        "noticeSeen": False,
        "recordCount": 0,
    }
    assert (await client.get(API)).json() == {"items": []}


async def test_onboarding_records_self_report_and_marks_notice(health_context):
    client, db, (user, _) = health_context
    authenticate(client, user)
    result = await client.post(
        f"{API}/onboarding", json={"status": "fair", "note": "最近睡得少"}
    )
    assert result.status_code == 200
    assert result.json() == {
        "collectionEnabled": True,
        "noticeSeen": True,
        "recordCount": 1,
    }
    items = (await client.get(API)).json()["items"]
    assert len(items) == 1
    assert items[0]["category"] == "general_status"
    assert items[0]["categoryLabel"] == "近期身体状态"
    assert items[0]["source"] == "onboarding"
    assert items[0]["content"] == "最近身体状态一般：最近睡得少"

    row = await db.scalar(select(HealthRecord).where(HealthRecord.user_id == user.id))
    assert row.content_ciphertext != items[0]["content"]
    assert decrypt_sensitive(row.content_ciphertext) == items[0]["content"]


async def test_onboarding_rejects_unknown_status(health_context):
    client, _, (user, _) = health_context
    authenticate(client, user)
    result = await client.post(f"{API}/onboarding", json={"status": "critical"})
    assert result.status_code == 422
    assert result.json()["code"] == "VALIDATION_ERROR"


async def test_skip_only_marks_notice_and_records_nothing(health_context):
    client, _, (user, _) = health_context
    authenticate(client, user)
    result = await client.patch(f"{API}/settings", json={"noticeSeen": True})
    assert result.json() == {
        "collectionEnabled": True,
        "noticeSeen": True,
        "recordCount": 0,
    }
    assert (await client.get(API)).json() == {"items": []}


async def test_disabling_collection_stops_context_but_keeps_records(health_context):
    client, db, (user, _) = health_context
    authenticate(client, user)
    await client.post(f"{API}/onboarding", json={"status": "poor"})
    assert await service.build_health_context(db, user.id) is not None

    patched = await client.patch(f"{API}/settings", json={"collectionEnabled": False})
    assert patched.json()["collectionEnabled"] is False
    assert await service.build_health_context(db, user.id) is None
    assert len((await client.get(API)).json()["items"]) == 1

    reenabled = await client.patch(f"{API}/settings", json={"collectionEnabled": True})
    assert reenabled.json()["collectionEnabled"] is True
    assert await service.build_health_context(db, user.id) is not None


async def test_records_are_isolated_between_users(health_context):
    client, _, (first, second) = health_context
    authenticate(client, first)
    created = await client.post(API, json={"category": "symptom", "content": "夜间失眠"})
    assert created.status_code == 201
    record_id = created.json()["id"]

    authenticate(client, second)
    assert (await client.get(API)).json() == {"items": []}
    assert (
        await client.patch(f"{API}/{record_id}", json={"content": "别人的记录"})
    ).status_code == 404
    assert (await client.delete(f"{API}/{record_id}")).status_code == 404

    authenticate(client, first)
    assert len((await client.get(API)).json()["items"]) == 1


async def test_duplicate_facts_are_stored_once(health_context):
    client, _, (user, _) = health_context
    authenticate(client, user)
    first = await client.post(API, json={"category": "allergy", "content": "对青霉素过敏"})
    second = await client.post(API, json={"category": "allergy", "content": " 对青霉素过敏 "})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get(API)).json()["items"]) == 1


async def test_edit_and_delete_record(health_context):
    client, _, (user, _) = health_context
    authenticate(client, user)
    record_id = (
        await client.post(API, json={"category": "symptom", "content": "夜间失眠"})
    ).json()["id"]

    patched = await client.patch(f"{API}/{record_id}", json={"content": "最近一周夜间失眠"})
    assert patched.status_code == 200
    assert patched.json()["content"] == "最近一周夜间失眠"
    assert patched.json()["source"] == "user"

    assert (await client.delete(f"{API}/{record_id}")).status_code == 204
    assert (await client.get(API)).json() == {"items": []}


@pytest.mark.parametrize(
    "payload",
    [
        {"category": "diagnosis", "content": "高血压"},
        {"category": "symptom", "content": "   "},
        {"category": "symptom", "content": "啊" * 501},
        {"category": "symptom", "content": "夜间失眠", "userId": str(uuid4())},
        {"content": "夜间失眠"},
    ],
)
async def test_invalid_records_are_rejected_atomically(health_context, payload):
    client, _, (user, _) = health_context
    authenticate(client, user)
    result = await client.post(API, json=payload)
    assert result.status_code == 422
    assert result.json()["code"] == "VALIDATION_ERROR"
    assert (await client.get(API)).json() == {"items": []}


async def test_extraction_stores_conversation_facts_once(health_context, monkeypatch):
    client, db, (user, _) = health_context
    authenticate(client, user)
    _, answer = await add_exchange(db, user, "我最近总口渴")
    calls: list[str] = []

    async def fake_extract(user_text, model, *, existing_facts=None):
        calls.append(user_text)
        return [
            ExtractedFact(category=HealthRecordCategory.SYMPTOM, content="最近经常口渴"),
            ExtractedFact(category=HealthRecordCategory.SYMPTOM, content="可能患有糖尿病"),
        ]

    monkeypatch.setattr(service, "extract_health_facts", fake_extract)
    monkeypatch.setattr(
        service, "extraction_model", AsyncMock(return_value=object())
    )
    payload = {
        "consultationId": str(answer.consultation_id),
        "messageId": str(answer.id),
    }

    result = await client.post(f"{API}/extract", json=payload)
    assert result.status_code == 200
    assert result.json() == {"stored": 1}
    # 抽取文本必须来自助手回答之前的那条用户提问。
    assert calls == ["我最近总口渴"]
    items = (await client.get(API)).json()["items"]
    assert [item["content"] for item in items] == ["最近经常口渴"]
    assert items[0]["source"] == "conversation"

    assert (await client.post(f"{API}/extract", json=payload)).json() == {"stored": 0}
    assert len(calls) == 1


async def test_extraction_skips_small_talk_and_foreign_messages(health_context, monkeypatch):
    client, db, (first, second) = health_context
    calls: list[str] = []

    async def fake_extract(user_text, model, *, existing_facts=None):
        calls.append(user_text)
        return []

    monkeypatch.setattr(service, "extract_health_facts", fake_extract)
    monkeypatch.setattr(
        service, "extraction_model", AsyncMock(return_value=object())
    )

    _, chat = await add_exchange(db, first, "你好", medical=False)
    authenticate(client, first)
    payload = {"consultationId": str(chat.consultation_id), "messageId": str(chat.id)}
    assert (await client.post(f"{API}/extract", json=payload)).json() == {"stored": 0}
    assert calls == []

    _, medical = await add_exchange(db, first, "我最近总口渴")
    authenticate(client, second)
    foreign = {"consultationId": str(medical.consultation_id), "messageId": str(medical.id)}
    assert (await client.post(f"{API}/extract", json=foreign)).status_code == 404
    assert calls == []


async def test_extraction_is_driven_by_the_assistant_flag(health_context, monkeypatch):
    """判定在助手回答上：传用户消息 id 被拒，助手未标记为医疗内容则不抽取。"""
    client, db, (user, _) = health_context
    authenticate(client, user)
    question, answer = await add_exchange(db, user, "我最近总口渴")
    calls: list[str] = []

    async def fake_extract(user_text, model, *, existing_facts=None):
        calls.append(user_text)
        return [ExtractedFact(category=HealthRecordCategory.SYMPTOM, content="最近经常口渴")]

    monkeypatch.setattr(service, "extract_health_facts", fake_extract)
    monkeypatch.setattr(
        service, "extraction_model", AsyncMock(return_value=object())
    )

    # 契约：messageId 必须是助手回答，传用户消息一律 404。
    user_payload = {
        "consultationId": str(question.consultation_id),
        "messageId": str(question.id),
    }
    assert (await client.post(f"{API}/extract", json=user_payload)).status_code == 404
    assert calls == []

    # 即使把用户消息强行标为医疗内容，只要助手回答没有这个标记就不抽取。
    question.is_medical_content = True
    answer.is_medical_content = False
    await db.flush()
    answer_payload = {
        "consultationId": str(answer.consultation_id),
        "messageId": str(answer.id),
    }
    assert (await client.post(f"{API}/extract", json=answer_payload)).json() == {"stored": 0}
    assert calls == []


async def test_extraction_respects_disabled_collection(health_context, monkeypatch):
    client, db, (user, _) = health_context
    authenticate(client, user)
    _, answer = await add_exchange(db, user, "我最近总口渴")
    calls: list[str] = []

    async def fake_extract(user_text, model, *, existing_facts=None):
        calls.append(user_text)
        return [ExtractedFact(category=HealthRecordCategory.SYMPTOM, content="最近经常口渴")]

    monkeypatch.setattr(service, "extract_health_facts", fake_extract)
    monkeypatch.setattr(
        service, "extraction_model", AsyncMock(return_value=object())
    )
    await client.patch(f"{API}/settings", json={"collectionEnabled": False})

    payload = {"consultationId": str(answer.consultation_id), "messageId": str(answer.id)}
    assert (await client.post(f"{API}/extract", json=payload)).json() == {"stored": 0}
    assert calls == []
    assert (await client.get(API)).json() == {"items": []}


async def test_health_context_is_bounded_and_framed_as_user_statements(health_context):
    client, db, (user, _) = health_context
    authenticate(client, user)
    for index in range(30):
        await client.post(
            API, json={"category": "symptom", "content": f"自述症状{index}号"}
        )
    block = await service.build_health_context(db, user.id)
    assert block is not None
    assert len(block) < 3000
    assert "不得据记录推断病因" in block
    assert "不得因为记录中存在某项情况而降低对红旗症状的警惕" in block
    # 30 条已超出注入上限，只应包含较新的记录，最早的一条必须被丢弃。
    assert "自述症状29号" in block
    assert "自述症状0号" not in block
