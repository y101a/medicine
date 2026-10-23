import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.registry import ModelConfig
from app.core.config import get_settings
from app.core.security import create_access_token, decrypt_sensitive, encrypt_sensitive
from app.models import Consultation, Gender, Message, User
from app.schemas.consultations import CreateMessage
from app.services import consultations
from app.services.auth import ACCESS_COOKIE


async def test_save_restore_pagination_idempotency_and_delete(profile_context):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    request = {"clientRequestId": str(uuid4())}
    created = await client.post("/api/v1/consultations", json=request)
    assert created.status_code == 201
    cid = created.json()["id"]
    url = f"/api/v1/consultations/{cid}"
    assert (await client.post("/api/v1/consultations", json=request)).json()["id"] == cid
    assert (await client.get(url + "/messages")).json()["items"] == []
    for i in range(3):
        body = {"clientRequestId": str(uuid4()), "content": f"  测试症状 {i}  "}
        result = await client.post(url + "/messages", json=body)
        assert result.status_code == 201
        assert result.json()["sequence"] == i + 1
        assert result.json()["content"] == f"测试症状 {i}"
        retry = await client.post(url + "/messages", json=body)
        assert retry.json()["id"] == result.json()["id"]
        body["content"] = "不同内容"
        assert (await client.post(url + "/messages", json=body)).status_code == 409
    detail = (await client.get(url)).json()
    assert detail["title"] == "测试症状 0"
    assert detail["messageCount"] == 3
    page = (await client.get(url + "/messages?limit=2")).json()
    assert [row["sequence"] for row in page["items"]] == [2, 3]
    assert page["hasMore"]
    older = (await client.get(url + "/messages?limit=2&before=2")).json()
    assert [row["sequence"] for row in older["items"]] == [1]
    assert not older["hasMore"]
    row = await db.scalar(select(Consultation).where(Consultation.id == created.json()["id"]))
    assert row.title_ciphertext != detail["title"]
    assert decrypt_sensitive(row.title_ciphertext) == detail["title"]
    stored = (await db.scalars(select(Message).where(Message.consultation_id == row.id))).all()
    assert all("测试症状" not in message.content_ciphertext for message in stored)
    await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    first = (await client.get("/api/v1/consultations?limit=1")).json()
    second = (await client.get("/api/v1/consultations?limit=1&offset=1")).json()
    assert first["hasMore"] and not second["hasMore"]
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (
        await db.scalar(
            select(func.count()).select_from(Message).where(Message.consultation_id == row.id)
        )
        == 0
    )


async def test_ownership_on_every_endpoint(profile_context):
    client, _, (first, second) = profile_context
    request = {"clientRequestId": str(uuid4())}
    assert (await client.post("/api/v1/consultations", json=request)).status_code == 401
    assert (await client.get("/api/v1/consultations")).status_code == 401
    client.cookies.set(ACCESS_COOKIE, create_access_token(first.id))
    created = (await client.post("/api/v1/consultations", json=request)).json()
    url = f"/api/v1/consultations/{created['id']}"
    body = {"clientRequestId": str(uuid4()), "content": "私有消息"}
    await client.post(url + "/messages", json=body)
    client.cookies.clear()
    for method, path, data in [
        ("GET", url, None),
        ("GET", url + "/messages", None),
        ("POST", url + "/messages", body),
        ("DELETE", url, None),
    ]:
        assert (await client.request(method, path, json=data)).status_code == 401
    client.cookies.set(ACCESS_COOKIE, create_access_token(second.id))
    assert (await client.get("/api/v1/consultations")).json()["items"] == []
    for method, path, data in [
        ("GET", url, None),
        ("GET", url + "/messages", None),
        ("POST", url + "/messages", body),
        ("DELETE", url, None),
    ]:
        assert (await client.request(method, path, json=data)).status_code == 404
    # The same client request ID is scoped to the owner, never to another account.
    assert (await client.post("/api/v1/consultations", json=request)).json()["id"] != created["id"]
    client.cookies.set(ACCESS_COOKIE, create_access_token(first.id))
    assert (await client.get(url)).json()["messageCount"] == 1


@pytest.mark.parametrize("natural_card", [False, True])
async def test_stream_answer_is_incremental_and_persisted(
    profile_context, monkeypatch, natural_card
):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    url = f"/api/v1/consultations/{created['id']}"
    await client.post(
        url + "/messages",
        json={"clientRequestId": str(uuid4()), "content": "持续头痛两天"},
    )

    selected_model = ModelConfig(
        id="glm-4.7-flash",
        name="智谱 GLM-4.7 Flash",
        provider="zhipuai",
        provider_name="智谱 AI",
        description="测试",
        base_url="https://example.test/v4",
        api_key=SecretStr("test-key"),
    )
    monkeypatch.setattr(
        "app.api.routes.consultations.get_model_for_user",
        AsyncMock(return_value=selected_model),
    )

    evidence = {
        "source_key": "developer_prototype_knowledge",
        "organization": "项目开发者",
        "title": "头痛原型资料",
        "canonical_url": "https://prototype.invalid/medical-knowledge/headache",
        "section_title": "常见表现",
        "content": "隔离测试证据",
        "similarity": 0.8,
        "trust_level": "prototype",
    }

    async def fake_generation_context(user_text, _db):
        assert user_text == "持续头痛两天"
        return {
            "triage_route": "continue",
            "triage_rule_version": "test",
            "triage_rule_ids": [],
            "triage_result": None,
            "next_step": "generation_ready",
            "retrieval_status": "completed",
            "retrieval_items": [evidence, {**evidence, "section_title": "重复文本块"}],
            "retrieval_error_code": None,
            "retrieval_intent": True,
            "retrieval_gate_reason": "medical_content",
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    monkeypatch.setattr(
        "app.api.routes.consultations.run_consultation_generation",
        fake_generation_context,
    )

    async def fake_stream(history, model, answer_format, rag_context, health_context=None):
        assert history[-1] == {"role": "user", "content": "持续头痛两天"}
        assert model is selected_model
        assert answer_format == "plain"
        assert rag_context is not None
        assert "隔离测试证据" in rag_context
        yield "先了解"
        yield "疼痛位置[来源2]。"

    monkeypatch.setattr("app.ai.provider.stream_chat", fake_stream)
    monkeypatch.setattr(
        "app.api.routes.consultations.check_answer_evidence",
        AsyncMock(side_effect=lambda _model, content, _sources: content),
    )
    response = await client.post(
        url + "/stream",
        json={"clientRequestId": str(uuid4()), "modelId": selected_model.id},
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["start", "delta", "done"]
    assert "".join(event.get("content", "") for event in events) == "先了解疼痛位置[来源2]。"
    assert events[-1]["message"]["role"] == "assistant"
    assert events[0]["model"]["id"] == selected_model.id
    assert events[-1]["message"]["provider"] == "zhipuai"
    assert events[-1]["message"]["modelId"] == selected_model.id
    assert events[-1]["message"]["modelName"] == selected_model.name
    assert events[-1]["message"]["generationStatus"] == "completed"
    assert events[-1]["message"]["answerFormat"] == "plain"
    assert events[-1]["message"]["medicalContent"] is True
    assert events[-1]["message"]["sourceMessageId"] is None
    assert events[0]["retrieval"]["status"] == "completed"
    assert events[0]["retrieval"]["webSearchStatus"] == "skipped"
    assert events[0]["retrieval"]["webSearchErrorCode"] is None
    assert [source["referenceNumber"] for source in events[0]["retrieval"]["sources"]] == [1, 2]
    assert events[-1]["message"]["citations"] == [
        {
            "referenceNumber": 2,
            "sourceKey": evidence["source_key"],
            "organization": evidence["organization"],
            "title": evidence["title"],
            "canonicalUrl": evidence["canonical_url"],
            "sectionTitle": "重复文本块",
            "similarity": evidence["similarity"],
            "trustLevel": evidence["trust_level"],
        }
    ]

    restored = (await client.get(url + "/messages")).json()["items"]
    assert [item["role"] for item in restored] == ["user", "assistant"]
    assert restored[-1]["content"] == "先了解疼痛位置[来源2]。"
    assert restored[-1]["modelId"] == selected_model.id
    assert restored[-1]["modelName"] == selected_model.name
    assert restored[-1]["citations"] == events[-1]["message"]["citations"]
    stored = await db.scalar(select(Message).where(Message.id == events[-1]["message"]["id"]))
    assert stored.citations_ciphertext
    assert evidence["title"] not in stored.citations_ciphertext
    assert (await client.post(
        url + "/stream",
        json={"clientRequestId": str(uuid4()), "modelId": selected_model.id},
    )).status_code == 409

    async def fake_card_stream(history, model, answer_format, rag_context, health_context=None):
        assert history[-1] == {"role": "user", "content": "持续头痛两天"}
        assert all(item["content"] != "先了解疼痛位置[来源2]。" for item in history)
        assert model is selected_model
        assert answer_format == "card"
        assert rag_context is not None
        yield "## 情况梳理\n持续头痛需要结合伴随表现判断。[来源1]"

    monkeypatch.setattr("app.ai.provider.stream_chat", fake_card_stream)
    if natural_card:
        await client.post(
            url + "/messages",
            json={"clientRequestId": str(uuid4()), "content": "把刚才的回答整理成卡片"},
        )
    card_response = await client.post(
        url + "/stream",
        json={
            "clientRequestId": str(uuid4()),
            "modelId": selected_model.id,
            **({} if natural_card else {
                "answerFormat": "card",
                "sourceMessageId": events[-1]["message"]["id"],
            }),
        },
    )
    assert card_response.status_code == 200
    card_events = [json.loads(line) for line in card_response.text.splitlines()]
    card_message = card_events[-1]["message"]
    assert card_message["answerFormat"] == "card"
    assert card_message["medicalContent"] is True
    assert card_message["sourceMessageId"] == events[-1]["message"]["id"]
    assert "情况梳理" in card_message["content"]

    duplicate = await client.post(
        url + "/stream",
        json={
            "clientRequestId": str(uuid4()),
            "modelId": selected_model.id,
            "answerFormat": "card",
            "sourceMessageId": events[-1]["message"]["id"],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "PATHOLOGY_CARD_EXISTS"

    restored_with_card = (await client.get(url + "/messages")).json()["items"]
    assert [item["role"] for item in restored_with_card] == (
        ["user", "assistant", "user", "assistant"] if natural_card
        else ["user", "assistant", "assistant"]
    )
    assert restored_with_card[-1]["sourceMessageId"] == events[-1]["message"]["id"]


async def test_structured_follow_up_is_validated_persisted_and_restored(
    profile_context, monkeypatch
):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    url = f"/api/v1/consultations/{created['id']}"
    await client.post(
        url + "/messages",
        json={"clientRequestId": str(uuid4()), "content": "头痛并且有些恶心"},
    )
    selected_model = ModelConfig(
        id="glm-4.7-flash",
        name="智谱 GLM-4.7 Flash",
        provider="zhipuai",
        provider_name="智谱 AI",
        description="测试",
        base_url="https://example.test/v4",
        api_key=SecretStr("test-key"),
    )
    monkeypatch.setattr(
        "app.api.routes.consultations.get_model_for_user",
        AsyncMock(return_value=selected_model),
    )
    evidence = {
        "source_key": "developer_prototype_knowledge",
        "organization": "项目开发者",
        "title": "头痛原型资料",
        "canonical_url": "https://prototype.invalid/medical-knowledge/headache",
        "section_title": "常见表现",
        "content": "隔离测试证据",
        "similarity": 0.8,
        "trust_level": "prototype",
    }

    async def fake_generation_context(_user_text, _db):
        return {
            "triage_route": "continue",
            "triage_rule_version": "test",
            "triage_rule_ids": [],
            "triage_result": None,
            "next_step": "generation_ready",
            "retrieval_status": "completed",
            "retrieval_items": [evidence],
            "retrieval_error_code": None,
            "retrieval_intent": True,
            "retrieval_gate_reason": "medical_content",
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    monkeypatch.setattr(
        "app.api.routes.consultations.run_consultation_generation",
        fake_generation_context,
    )
    payload = {
        "intro": "为了更准确地提供科普信息，请补充以下情况",
        "questions": [
            {
                "id": "location",
                "label": "疼痛位置在哪里？",
                "type": "single_choice",
                "required": True,
                "options": [
                    {"value": "one_side", "label": "单侧"},
                    {"value": "both_sides", "label": "双侧"},
                ],
            },
            {
                "id": "severity",
                "label": "疼痛程度是多少？",
                "type": "scale",
                "required": True,
                "options": [],
                "min": 1,
                "max": 10,
            },
        ],
    }

    async def fake_stream(history, model, answer_format, rag_context, health_context=None):
        assert answer_format == "card"
        assert rag_context is not None
        assert '"id": "来源1"' in rag_context
        assert "隔离测试证据" in rag_context
        yield "先提供一段普通说明。\n\n[[FOLLOW\\_"
        yield "UP\\_CARD]]\n"
        yield json.dumps(payload, ensure_ascii=False).replace("_", r"\_")

    monkeypatch.setattr("app.ai.provider.stream_chat", fake_stream)
    response = await client.post(
        url + "/stream",
        json={
            "clientRequestId": str(uuid4()),
            "modelId": selected_model.id,
            "answerFormat": "card",
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["start", "done"]
    assert events[0]["retrieval"]["status"] == "completed"
    assert events[0]["retrieval"]["sources"][0]["trustLevel"] == "prototype"
    assert "content" not in events[0]["retrieval"]["sources"][0]
    message = events[-1]["message"]
    assert message["citations"] == []
    assert message["followUp"]["intro"] == payload["intro"]
    assert [question["id"] for question in message["followUp"]["questions"]] == [
        "location",
        "severity",
    ]
    assert message["followUp"]["questions"][0]["options"] == payload["questions"][0][
        "options"
    ]
    assert message["followUp"]["questions"][1]["min"] == 1
    assert message["followUp"]["questions"][1]["max"] == 10
    assert "疼痛位置在哪里" in message["content"]
    assert "[[FOLLOW_UP_CARD]]" not in message["content"]

    restored = (await client.get(url + "/messages")).json()["items"][-1]
    assert restored["followUp"] == message["followUp"]
    assert restored["generationStatus"] == "completed"


async def test_emergency_triage_is_encrypted_and_blocks_model_generation(profile_context):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    url = f"/api/v1/consultations/{created['id']}"
    response = await client.post(
        url + "/messages",
        json={"clientRequestId": str(uuid4()), "content": "突然胸痛，喘不上气"},
    )
    assert response.status_code == 201
    triage = response.json()["triage"]
    assert triage["level"] == "emergency"
    assert "acute_chest_pain" in triage["ruleIds"]
    assert "severe_breathing_problem" in triage["ruleIds"]

    stored = await db.scalar(
        select(Message).where(Message.id == response.json()["id"])
    )
    assert stored.triage_ciphertext
    assert "胸痛" not in stored.triage_ciphertext

    blocked = await client.post(
        url + "/stream",
        json={"clientRequestId": str(uuid4()), "modelId": "not-configured"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "EMERGENCY_TRIAGE_ACTIVE"


async def test_available_models_are_authenticated_and_safe(profile_context, monkeypatch):
    client, _, (user, _) = profile_context
    configured = ModelConfig(
        id="glm-4.7-flash",
        name="智谱 GLM-4.7 Flash",
        provider="zhipuai",
        provider_name="智谱 AI",
        description="免费轻量模型",
        base_url="https://example.test/v4",
        api_key=SecretStr("must-not-leak"),
    )
    monkeypatch.setattr(
        "app.api.routes.models.available_models_for_user",
        AsyncMock(return_value=[configured]),
    )
    assert (await client.get("/api/v1/models")).status_code == 401
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    response = await client.get("/api/v1/models")
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": configured.id,
                "name": configured.name,
                "provider": configured.provider,
                "providerName": configured.provider_name,
                "description": configured.description,
                "isDefault": True,
                "keySource": "server",
            }
        ]
    }
    assert "must-not-leak" not in response.text


async def test_unregistered_model_is_rejected_before_generation(profile_context):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    response = await client.post(
        f"/api/v1/consultations/{created['id']}/stream",
        json={"clientRequestId": str(uuid4()), "modelId": "untrusted/model"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "MODEL_NOT_AVAILABLE"


@pytest.mark.parametrize(
    "extra",
    [
        {"content": ""},
        {"content": "  "},
        {"content": "x" * 2001},
        {"content": None},
        {"role": "assistant"},
        {"user_id": str(uuid4())},
    ],
)
async def test_invalid_message_not_saved(profile_context, extra):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    url = f"/api/v1/consultations/{created['id']}"
    response = await client.post(
        url + "/messages",
        json={
            "clientRequestId": str(uuid4()),
            "content": "测试",
            **extra,
        },
    )
    assert response.status_code == 422
    assert (await client.get(url)).json()["messageCount"] == 0


@pytest.mark.parametrize(
    ("local_status", "web_status", "web_error"),
    [
        ("empty", "empty", None),
        ("empty", "failed", "WEB_SEARCH_TIMEOUT"),
        ("failed", "skipped", None),
    ],
)
@pytest.mark.parametrize("question,expected_format", [
    ("甲状腺结节科普", "plain"),
    ("帮我生成一张头痛科普卡片", "card"),
    ("不要生成头痛卡片", "plain"),
])
async def test_stream_without_evidence_never_persists_fake_citations(
    profile_context, monkeypatch, local_status, web_status, web_error,
    question, expected_format,
):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    url = f"/api/v1/consultations/{created['id']}"
    await client.post(
        url + "/messages",
        json={"clientRequestId": str(uuid4()), "content": question},
    )
    selected = ModelConfig(
        id="test-model", name="测试模型", provider="test",
        provider_name="测试", description="隔离测试",
        base_url="https://example.test/v1", api_key=SecretStr("test-only"),
    )
    monkeypatch.setattr(
        "app.api.routes.consultations.get_model_for_user",
        AsyncMock(return_value=selected),
    )

    async def fake_context(_text, _db):
        return {
            "triage_route": "continue",
            "triage_rule_version": "test",
            "triage_rule_ids": [],
            "triage_result": None,
            "next_step": "generation_ready",
            "retrieval_status": local_status,
            "retrieval_items": [],
            "retrieval_error_code": "EMBEDDING_TIMEOUT" if local_status == "failed" else None,
            "retrieval_intent": True,
            "retrieval_gate_reason": "medical_content",
            "web_search_status": web_status,
            "web_search_error_code": web_error,
        }

    async def fake_stream(_history, _model, _answer_format, rag_context, health_context=None):
        assert _answer_format == expected_format
        assert rag_context is None
        yield "目前没有可核验的参考资料，请咨询医生。"

    monkeypatch.setattr(
        "app.api.routes.consultations.run_consultation_generation", fake_context,
    )
    monkeypatch.setattr("app.ai.provider.stream_chat", fake_stream)
    response = await client.post(
        url + "/stream",
        json={"clientRequestId": str(uuid4()), "modelId": selected.id},
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["type"] == "start"
    assert events[0]["retrieval"]["status"] == local_status
    assert events[0]["retrieval"]["webSearchStatus"] == web_status
    assert events[0]["retrieval"]["webSearchErrorCode"] == web_error
    assert events[0]["retrieval"]["sources"] == []
    assert events[-1]["message"]["citations"] == []
    assert events[-1]["message"]["answerFormat"] == expected_format
    restored = (await client.get(url + "/messages")).json()["items"]
    assert restored[-1]["answerFormat"] == expected_format


async def test_named_disease_without_evidence_never_calls_model(profile_context, monkeypatch):
    client, _, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    url = f"/api/v1/consultations/{created['id']}"
    await client.post(
        url + "/messages",
        json={"clientRequestId": str(uuid4()), "content": "法布雷病是什么？有哪些常见表现？"},
    )
    selected = ModelConfig(
        id="test-model", name="测试模型", provider="test",
        provider_name="测试", description="隔离测试",
        base_url="https://example.test/v1", api_key=SecretStr("test-only"),
    )
    monkeypatch.setattr(
        "app.api.routes.consultations.get_model_for_user",
        AsyncMock(return_value=selected),
    )

    async def no_evidence(_text, _db):
        return {
            "triage_route": "continue", "triage_rule_version": "test",
            "triage_rule_ids": [], "triage_result": None,
            "next_step": "generation_ready", "retrieval_status": "empty",
            "retrieval_items": [], "retrieval_error_code": None,
            "retrieval_intent": True, "retrieval_gate_reason": "medical_content",
            "web_search_status": "skipped", "web_search_error_code": None,
        }

    async def unexpected_model(*_args, **_kwargs):
        raise AssertionError("无资料的具体病名不应调用模型补写医学事实")
        yield ""  # pragma: no cover

    monkeypatch.setattr(
        "app.api.routes.consultations.run_consultation_generation", no_evidence,
    )
    monkeypatch.setattr("app.ai.provider.stream_chat", unexpected_model)
    response = await client.post(
        url + "/stream",
        json={"clientRequestId": str(uuid4()), "modelId": selected.id},
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done"
    assert "没有完成联网检索" in events[-1]["message"]["content"]
    assert "不能可靠地列出" in events[-1]["message"]["content"]
    assert events[-1]["message"]["citations"] == []
    saved = (await client.get(url + "/messages")).json()["items"][-1]
    assert saved["content"] == events[-1]["message"]["content"]


async def test_committed_messages_survive_new_connection_and_concurrent_retry():
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid4()
    try:
        async with sessions() as db:
            db.add(
                User(
                    id=uid,
                    username=uid.hex[:20],
                    username_normalized=uid.hex[:20],
                    real_name_ciphertext=encrypt_sensitive("并发测试"),
                    phone_ciphertext=encrypt_sensitive("13800138000"),
                    phone_fingerprint=uid.hex,
                    id_card_ciphertext=encrypt_sensitive("11010519491231002X"),
                    id_card_fingerprint=uid.hex,
                    gender=Gender.PRIVATE,
                )
            )
            await db.commit()
            conversation = await consultations.create(db, uid, uuid4())
        payload = CreateMessage(clientRequestId=uuid4(), content="并发保存测试")

        async def send():
            async with sessions() as db:
                return await consultations.append_message(db, uid, conversation.id, payload)

        results = await asyncio.gather(send(), send(), send())
        assert len({result.id for result in results}) == 1
        async with sessions() as db:
            restored = await consultations.list_messages(db, uid, conversation.id, None, 50)
            assert [row.content for row in restored.items] == ["并发保存测试"]
            assert (await consultations.owned(db, uid, conversation.id)).message_count == 1
    finally:
        async with sessions() as db:
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
        await engine.dispose()
