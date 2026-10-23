"""Old-message compaction stays local, encrypted, scoped and outside triage."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.ai.registry import ModelConfig
from app.core.errors import AppError
from app.core.security import create_access_token, decrypt_sensitive, encrypt_sensitive
from app.models import Consultation, ConsultationMemory, Message
from app.services import consultations, conversation_memory
from app.services.auth import ACCESS_COOKIE


def test_local_excerpts_keep_user_words_without_inventing_medical_facts():
    items = conversation_memory._candidates(
        1, "我对青霉素过敏，电话13800138000。请记住以后回答要简短。"
    )
    rendered = conversation_memory._render(items)
    assert rendered is not None
    assert "13800138000" not in rendered
    assert "青霉素过敏" in rendered
    assert "已核实病历" in rendered
    assert "第1条用户消息" in rendered


def test_selection_keeps_important_older_and_recent_context_with_a_hard_bound():
    items = [
        {"sequence": 1, "text": "请记住我以后只想看中文解释。", "score": 3},
        *[
            {"sequence": index, "text": f"第{index}条普通上下文", "score": 0}
            for index in range(2, 30)
        ],
    ]
    selected = conversation_memory._select(items)
    assert len(selected) <= conversation_memory.MAX_EXCERPTS
    assert any(item["sequence"] == 1 for item in selected)
    assert any(item["sequence"] == 29 for item in selected)
    assert len(conversation_memory._render(selected) or "") <= 1200


def test_importance_prefers_explicit_health_facts_over_polite_or_generic_words():
    assert conversation_memory._candidates(1, "你好。谢谢。继续之前的话题。") == []
    assert conversation_memory._candidates(2, "我想问个问题，之前看到一篇文章。") == []
    allergy = conversation_memory._candidates(3, "我对青霉素过敏。")
    preference = conversation_memory._candidates(4, "以后回答请使用简短中文。")
    assert allergy[0]["score"] > preference[0]["score"]
    assert conversation_memory._candidates(5, "我没有青霉素过敏史。") == [
        {
            "sequence": 5,
            "text": "我没有青霉素过敏史。",
            "score": allergy[0]["score"],
            "category": "allergy",
            "source": "user_statement",
            "recorded_at": None,
        }
    ]


def test_selection_deduplicates_and_keeps_current_and_historical_words_verbatim():
    items = [
        *conversation_memory._candidates(1, "我以前没有药物过敏。"),
        *conversation_memory._candidates(2, "我现在对青霉素过敏。"),
        *conversation_memory._candidates(3, "我现在对青霉素过敏！"),
    ]
    selected = conversation_memory._select(items)
    assert len(selected) == 2
    assert any("以前没有药物过敏" in item["text"] for item in selected)
    assert any("现在对青霉素过敏" in item["text"] for item in selected)
    assert conversation_memory._load_items(
        encrypt_sensitive(json.dumps([{"sequence": 1, "text": "旧摘要", "score": 1}]))
    ) is None


def test_structured_items_preserve_source_time_and_negated_original_wording():
    when = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
    items = conversation_memory._candidates(7, "我没有青霉素过敏史，电话13800138000。", when)
    assert items[0]["category"] == "allergy"
    assert items[0]["source"] == "user_statement"
    assert items[0]["recorded_at"] == when.isoformat()
    assert "没有青霉素过敏史" in str(items[0]["text"])
    assert "13800138000" not in str(items[0]["text"])
    rendered = conversation_memory._render(items)
    assert rendered is not None and "过敏相关自述" in rendered
    assert "第7条用户消息" in rendered
    assert "记录于2026-10-14" in rendered
    assert conversation_memory._load_items(
        encrypt_sensitive(json.dumps({"version": 2, "items": items}))
    ) is None
    assert conversation_memory._candidates(8, "我想了解青霉素过敏是什么。") == []
    assert conversation_memory._candidates(9, "我看到文章介绍过敏的症状。") == []


async def _seed_long_chat(db, user_id):
    created = await consultations.create(db, user_id, uuid4())
    row = await db.get(Consultation, created.id)
    assert row is not None
    row.message_count = 35
    messages = []
    for sequence in range(1, 36):
        if sequence == 1:
            content = "我对青霉素过敏，电话13800138000。"
        elif sequence == 3:
            content = "以后回答请使用简短中文。"
        elif sequence == 35:
            content = "继续之前的话题"
        else:
            content = f"第{sequence}条测试消息" + "这是很长的补充。" * 60
        messages.append(
            Message(
                id=uuid4(),
                consultation_id=created.id,
                client_request_id=uuid4(),
                sequence=sequence,
                role="user" if sequence % 2 else "assistant",
                content_ciphertext=encrypt_sensitive(content),
            )
        )
    db.add_all(messages)
    await db.commit()
    return created.id


async def test_summary_is_encrypted_incremental_and_owner_scoped(profile_context):
    _, db, (first, second) = profile_context
    cid = await _seed_long_chat(db, first.id)
    history, _, _, first_sequence = await consultations.ai_history(db, first.id, cid, limit=30)
    assert len(history) == 30
    assert first_sequence == 6
    assert history[-1]["content"] == "继续之前的话题"

    block = await conversation_memory.build_context(db, first.id, cid, first_sequence)
    assert block is not None
    assert "青霉素过敏" in block
    assert "13800138000" not in block
    stored = await db.get(ConsultationMemory, cid)
    assert stored is not None
    assert stored.covered_through_sequence == 5
    assert "青霉素过敏" not in stored.summary_ciphertext
    assert "青霉素过敏" in decrypt_sensitive(stored.summary_ciphertext)

    stored.summary_ciphertext = encrypt_sensitive(
        json.dumps([{"sequence": 1, "text": "你好，请记住", "score": 2}])
    )
    await db.commit()
    rebuilt = await conversation_memory.build_context(db, first.id, cid, first_sequence)
    assert rebuilt is not None and "青霉素过敏" in rebuilt
    assert "你好，请记住" not in rebuilt
    await db.refresh(stored)
    payload = json.loads(decrypt_sensitive(stored.summary_ciphertext))
    assert payload["version"] == 3
    assert payload["items"][0]["recorded_at"] is not None
    assert payload["items"][0]["source"] == "user_statement"
    assert payload["items"][0]["category"] == "allergy"

    with pytest.raises(AppError) as error:
        await conversation_memory.build_context(db, second.id, cid, first_sequence)
    assert error.value.status_code == 404

    chat = await db.get(Consultation, cid)
    assert chat is not None
    chat.message_count = 37
    db.add_all(
        [
            Message(
                consultation_id=cid,
                client_request_id=uuid4(),
                sequence=sequence,
                role="assistant" if sequence == 36 else "user",
                content_ciphertext=encrypt_sensitive(f"第{sequence}条测试消息"),
            )
            for sequence in (36, 37)
        ]
    )
    await db.commit()
    _, _, _, later_first = await consultations.ai_history(db, first.id, cid, limit=30)
    assert later_first == 8
    assert await conversation_memory.build_context(db, first.id, cid, later_first)
    await db.refresh(stored)
    assert stored.covered_through_sequence == 7

    await db.execute(delete(Consultation).where(Consultation.id == cid))
    await db.flush()
    assert (
        await db.scalar(
            select(ConsultationMemory.consultation_id).where(
                ConsultationMemory.consultation_id == cid
            )
        )
        is None
    )


async def test_stream_receives_old_excerpts_as_user_data_not_system_prompt(
    profile_context, monkeypatch
):
    client, db, (user, _) = profile_context
    cid = await _seed_long_chat(db, user.id)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    model = ModelConfig(
        id="qwen3.8-flash",
        name="test model",
        provider="qwen",
        provider_name="test",
        description="test",
        base_url="https://example.test/v1",
        api_key=SecretStr("test-key"),
    )
    monkeypatch.setattr(
        "app.api.routes.consultations.get_model_for_user", AsyncMock(return_value=model)
    )

    async def fake_graph(_text, _db):
        return {
            "triage_route": "continue",
            "retrieval_status": "skipped",
            "retrieval_items": [],
            "retrieval_error_code": None,
            "retrieval_intent": False,
            "retrieval_gate_reason": "small_talk",
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    monkeypatch.setattr("app.api.routes.consultations.run_consultation_generation", fake_graph)

    async def fake_stream(history, _model, _format, _rag, private_context=None):
        assert history[0]["role"] == "user"
        assert "青霉素过敏" in history[0]["content"]
        assert "已核实病历" in history[0]["content"]
        assert history[-1]["content"] == "继续之前的话题"
        assert private_context is None
        yield "这是测试回答。"

    monkeypatch.setattr("app.ai.provider.stream_chat", fake_stream)
    response = await client.post(
        f"/api/v1/consultations/{cid}/stream",
        json={"clientRequestId": str(uuid4()), "modelId": model.id},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done"
