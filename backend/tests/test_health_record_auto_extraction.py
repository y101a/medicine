"""服务端自动抽取（对话事件驱动）的链路、幂等与可观察性测试。

覆盖用户 2026-09-30 上报的缺陷：采集开着、用户明确自述，但一轮对话结束后什么都不落库。
这里的用例**不调用** ``POST /health-records/extract``（前端那条 fire-and-forget 路径），
全部走服务端回答完成链路，以证明抽取不再依赖浏览器。
"""

import json
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.health_extract import ExtractedFact
from app.ai.registry import ModelConfig
from app.api.routes import consultations as consultations_route
from app.api.routes.consultations import stream_answer
from app.core.errors import AppError
from app.core.security import create_access_token, decrypt_sensitive, encrypt_sensitive
from app.models import (
    Consultation,
    HealthRecord,
    HealthRecordCategory,
    HealthRecordSource,
    Message,
    User,
)
from app.schemas.consultations import CreateGeneration
from app.services import health_records as service
from app.services.auth import ACCESS_COOKIE

API = "/api/v1/health-records"
EXTRACT_LOG_CODES = "health_record_extraction"


def _selected_model() -> ModelConfig:
    return ModelConfig(
        id="test-extraction-model",
        name="测试模型",
        provider="test",
        provider_name="测试服务商",
        description="测试",
        base_url="https://example.test/v1",
        api_key=SecretStr("test-key"),
    )


@asynccontextmanager
async def _reuse_transaction_session(db: AsyncSession):
    """抽取任务借用测试事务里的同一个会话；不关闭它，测试后面还要继续读。"""

    yield db


def _enable_server_trigger(monkeypatch, db: AsyncSession, *, facts=None, error=None) -> list[str]:
    """打开服务端派发，并把抽取会话指向事务内测试会话。"""

    calls: list[str] = []

    async def fake_extract(user_text, model, *, existing_facts=None):
        calls.append(user_text)
        if error is not None:
            raise error
        return list(facts or [])

    monkeypatch.setattr(service, "EXTRACTION_SCHEDULING_ENABLED", True)
    monkeypatch.setattr(
        service, "EXTRACTION_SESSION_FACTORY", lambda: _reuse_transaction_session(db)
    )
    monkeypatch.setattr(service, "extract_health_facts", fake_extract)
    monkeypatch.setattr(service, "extraction_model", AsyncMock(return_value=object()))
    return calls


def _patch_answer_generation(monkeypatch, *, gate_reason: str = "non_medical_content") -> None:
    """把回答生成替换成不触网的最小实现；门控原因默认取“非医疗内容”。

    ``non_medical_content`` 正是线上对「我最近总口渴」的真实取值：旧实现据此跳过抽取，
    所以这个默认值是本缺陷的回归点，而不是随手写的桩。
    """

    monkeypatch.setattr(
        "app.api.routes.consultations.get_model_for_user",
        AsyncMock(return_value=_selected_model()),
    )

    async def fake_graph(_user_text, _db):
        return {
            "triage_route": "continue",
            "triage_rule_version": "test",
            "triage_rule_ids": [],
            "triage_result": None,
            "next_step": "generation_ready",
            "retrieval_status": "completed",
            "retrieval_items": [],
            "retrieval_error_code": None,
            "retrieval_intent": gate_reason == "medical_content",
            "retrieval_gate_reason": gate_reason,
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    monkeypatch.setattr(consultations_route, "run_consultation_generation", fake_graph)

    async def fake_stream(_history, _model, _answer_format, _rag_context, _health_context=None):
        yield "先了解"
        yield "一下。"

    monkeypatch.setattr("app.ai.provider.stream_chat", fake_stream)


async def _create_consultation_with_question(client: AsyncClient, content: str) -> tuple[str, str]:
    created = (
        await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    ).json()
    url = f"/api/v1/consultations/{created['id']}"
    await client.post(
        url + "/messages",
        json={"clientRequestId": str(uuid4()), "content": content},
    )
    return created["id"], url


async def _store_exchange(
    db: AsyncSession, user: User, text: str, *, medical: bool = False
) -> tuple[Message, Message]:
    """直接落一条问答（助手标记默认 False，即线上对这类自述的真实取值）。"""

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


async def _records(db: AsyncSession, user_id: UUID) -> list[tuple]:
    rows = await db.scalars(select(HealthRecord).where(HealthRecord.user_id == user_id))
    return [(row.category, decrypt_sensitive(row.content_ciphertext), row.source) for row in rows]


def _thirsty_facts() -> list[ExtractedFact]:
    return [ExtractedFact(category=HealthRecordCategory.SYMPTOM, content="最近经常口渴")]


async def test_completed_turn_stores_self_report_without_any_frontend_call(
    profile_context, monkeypatch
):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    _, url = await _create_consultation_with_question(client, "我最近总口渴")
    _patch_answer_generation(monkeypatch)
    calls = _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())

    response = await client.post(
        url + "/stream",
        json={"clientRequestId": str(uuid4()), "modelId": "test-extraction-model"},
    )
    assert response.status_code == 200
    assert [json.loads(line)["type"] for line in response.text.splitlines()][-1] == "done"

    # 全程没有调用 /health-records/extract：记录只能来自服务端派发。
    await service.drain_scheduled_extractions()

    assert calls == ["我最近总口渴"]
    assert await _records(db, user.id) == [
        (HealthRecordCategory.SYMPTOM, "最近经常口渴", HealthRecordSource.CONVERSATION)
    ]


async def test_generator_closed_mid_answer_still_extracts(profile_context, monkeypatch):
    """浏览器中途断开（生成器被关闭）时，回答完成链路的 finally 仍然派发抽取。"""

    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    consultation_id, _ = await _create_consultation_with_question(client, "我最近总口渴")
    _patch_answer_generation(monkeypatch)
    _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())

    response = await stream_answer(
        cid=UUID(consultation_id),
        payload=CreateGeneration(clientRequestId=uuid4(), modelId="test-extraction-model"),
        user=user,
        db=db,
    )
    iterator = response.body_iterator
    assert json.loads(await iterator.__anext__())["type"] == "start"
    assert json.loads(await iterator.__anext__())["type"] == "delta"
    await iterator.aclose()

    await service.drain_scheduled_extractions()

    assert await _records(db, user.id) == [
        (HealthRecordCategory.SYMPTOM, "最近经常口渴", HealthRecordSource.CONVERSATION)
    ]


async def test_inference_advice_and_identity_are_dropped(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    _, answer = await _store_exchange(db, user, "我最近总口渴")
    _enable_server_trigger(
        monkeypatch,
        db,
        facts=[
            ExtractedFact(category=HealthRecordCategory.SYMPTOM, content="最近经常口渴"),
            ExtractedFact(category=HealthRecordCategory.SYMPTOM, content="可能患有糖尿病"),
            ExtractedFact(category=HealthRecordCategory.OTHER, content="建议每天测血糖"),
            ExtractedFact(
                category=HealthRecordCategory.OTHER, content="患者身份证11010519491231002X"
            ),
        ],
    )

    result = await client.post(
        f"{API}/extract",
        json={"consultationId": str(answer.consultation_id), "messageId": str(answer.id)},
    )

    assert result.json() == {"stored": 1, "status": "stored", "reason": None}
    assert await _records(db, user.id) == [
        (HealthRecordCategory.SYMPTOM, "最近经常口渴", HealthRecordSource.CONVERSATION)
    ]


async def test_assistant_medical_flag_cannot_force_or_block_extraction(
    profile_context, monkeypatch
):
    """助手标记既不能强行触发，也不能阻止；判定只看用户消息本身。"""

    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))

    # 打招呼被强行标成医疗内容：仍然不抽取。
    _, chat = await _store_exchange(db, user, "你好", medical=True)
    calls = _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())
    skipped = await client.post(
        f"{API}/extract",
        json={"consultationId": str(chat.consultation_id), "messageId": str(chat.id)},
    )
    assert skipped.json() == {"stored": 0, "status": "skipped", "reason": "social-only"}
    assert calls == []

    # 真实自述但助手标记为 False（线上真实取值）：仍然抽取。
    _, thirsty = await _store_exchange(db, user, "我最近总口渴", medical=False)
    stored = await client.post(
        f"{API}/extract",
        json={"consultationId": str(thirsty.consultation_id), "messageId": str(thirsty.id)},
    )
    assert stored.json() == {"stored": 1, "status": "stored", "reason": None}
    assert calls == ["我最近总口渴"]


async def test_product_capability_question_creates_no_record(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    _, url = await _create_consultation_with_question(client, "你会自动定期更新健康记录吗")
    _patch_answer_generation(monkeypatch)
    calls = _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())

    response = await client.post(
        url + "/stream",
        json={"clientRequestId": str(uuid4()), "modelId": "test-extraction-model"},
    )

    assert response.status_code == 200
    await service.drain_scheduled_extractions()
    assert calls == []
    assert await _records(db, user.id) == []


async def test_repeated_trigger_is_idempotent(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    question, answer = await _store_exchange(db, user, "我最近总口渴")
    calls = _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())
    payload = {
        "consultationId": str(answer.consultation_id),
        "messageId": str(answer.id),
    }

    assert (await client.post(f"{API}/extract", json=payload)).json()["stored"] == 1
    assert (await client.post(f"{API}/extract", json=payload)).json() == {
        "stored": 0,
        "status": "skipped",
        "reason": "already-extracted",
    }

    # 服务端派发同一条消息（前端也可能同时再调一次）同样只产生一条记录。
    service.schedule_conversation_extraction(
        user_id=user.id, user_text="我最近总口渴", message_id=question.id
    )
    await service.drain_scheduled_extractions()

    assert calls == ["我最近总口渴"]
    assert len(await _records(db, user.id)) == 1


async def test_retriggering_an_older_message_does_not_call_the_model_again(
    profile_context, monkeypatch
):
    """``last_extracted_message_id`` 只记最近一条，较早消息的重触发不能白跑模型。

    开发库真实链路验证时暴露过：处理完更新的消息后，回过头重触发第一条会重新抽取
    （记录被 ``content_hash`` 兜住，但幂等不成立，还多花一次调用）。记录上的
    ``source_message_id`` 才是持久证据。
    """

    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    first_question, first_answer = await _store_exchange(db, user, "我最近总口渴")
    calls = _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())
    first_payload = {
        "consultationId": str(first_answer.consultation_id),
        "messageId": str(first_answer.id),
    }
    assert (await client.post(f"{API}/extract", json=first_payload)).json()["stored"] == 1

    # 又处理了一条更新的消息：幂等标记随之前移。
    _, later_answer = await _store_exchange(db, user, "我最近总口渴")
    later_payload = {
        "consultationId": str(later_answer.consultation_id),
        "messageId": str(later_answer.id),
    }
    assert (await client.post(f"{API}/extract", json=later_payload)).json()["status"] == "stored"
    calls_before_retrigger = len(calls)

    assert (await client.post(f"{API}/extract", json=first_payload)).json() == {
        "stored": 0,
        "status": "skipped",
        "reason": "already-extracted",
    }
    assert len(calls) == calls_before_retrigger
    assert len(await _records(db, user.id)) == 1

    # 服务端派发也要走同一判定。
    service.schedule_conversation_extraction(
        user_id=user.id, user_text="我最近总口渴", message_id=first_question.id
    )
    await service.drain_scheduled_extractions()
    assert len(calls) == calls_before_retrigger


async def test_disabled_collection_blocks_the_server_trigger_without_calling_the_model(
    profile_context, monkeypatch
):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    question, _ = await _store_exchange(db, user, "我最近总口渴")
    calls = _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())
    assert (await client.patch(f"{API}/settings", json={"collectionEnabled": False})).json()[
        "collectionEnabled"
    ] is False

    service.schedule_conversation_extraction(
        user_id=user.id, user_text="我最近总口渴", message_id=question.id
    )
    await service.drain_scheduled_extractions()

    assert calls == []
    assert await _records(db, user.id) == []


async def test_provider_failure_is_observable_and_logs_no_plaintext(
    profile_context, monkeypatch, caplog
):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    _, answer = await _store_exchange(db, user, "我最近总口渴（这句明文不得进日志）")
    _enable_server_trigger(
        monkeypatch,
        db,
        error=AppError(502, "AI_PROVIDER_ERROR", "健康记录提取调用失败"),
    )

    with caplog.at_level(logging.INFO, logger="app.services.health_records"):
        result = await client.post(
            f"{API}/extract",
            json={"consultationId": str(answer.consultation_id), "messageId": str(answer.id)},
        )

    assert result.json() == {"stored": 0, "status": "failed", "reason": "AI_PROVIDER_ERROR"}
    assert await _records(db, user.id) == []
    assert EXTRACT_LOG_CODES in caplog.text
    assert "AI_PROVIDER_ERROR" in caplog.text
    assert "我最近总口渴" not in caplog.text
    assert "test-key" not in caplog.text


async def test_detached_task_failure_never_surfaces_and_is_logged(
    profile_context, monkeypatch, caplog
):
    _, db, (user, _) = profile_context
    _enable_server_trigger(monkeypatch, db, facts=_thirsty_facts())

    @asynccontextmanager
    async def broken_session():
        raise OSError("session unavailable")
        yield  # pragma: no cover - 仅用于类型/语法完整

    monkeypatch.setattr(service, "EXTRACTION_SESSION_FACTORY", broken_session)

    with caplog.at_level(logging.WARNING, logger="app.services.health_records"):
        task = service.schedule_conversation_extraction(
            user_id=user.id, user_text="我最近总口渴", message_id=uuid4()
        )
        assert task is not None
        await service.drain_scheduled_extractions()

    assert "code=scheduled-task" in caplog.text
    assert await _records(db, user.id) == []


async def test_answer_still_completes_when_extraction_fails(profile_context, monkeypatch, caplog):
    client, db, (user, _) = profile_context
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    _, url = await _create_consultation_with_question(client, "我最近总口渴")
    _patch_answer_generation(monkeypatch)
    _enable_server_trigger(
        monkeypatch,
        db,
        error=AppError(502, "AI_PROVIDER_ERROR", "健康记录提取调用失败"),
    )

    with caplog.at_level(logging.INFO, logger="app.services.health_records"):
        response = await client.post(
            url + "/stream",
            json={"clientRequestId": str(uuid4()), "modelId": "test-extraction-model"},
        )
        await service.drain_scheduled_extractions()

    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    assert events[-1]["type"] == "done"
    assert "".join(event.get("content", "") for event in events) == "先了解一下。"
    assert "AI_PROVIDER_ERROR" in caplog.text
    assert await _records(db, user.id) == []
