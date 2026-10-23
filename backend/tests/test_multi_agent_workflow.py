"""P0 coordinated workflow contracts; external model calls are mocked."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from app.ai import consultation_evidence_reviewer, consultation_planner
from app.ai.bounded_workflow_plan import validate_workflow_plan
from app.ai.registry import ModelConfig
from app.ai.workflow_progress import consultation_workflow, document_workflow
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import GeneratedDocument
from app.rag.retrieval import RetrievalCitation, RetrievalResult
from app.services import document_generations as generation_service
from app.services.auth import ACCESS_COOKIE
from app.services.document_generation_content import (
    DocumentContentPlan,
    DocumentOutline,
    DocumentReview,
    plan_document_outline,
    review_document_draft,
    revise_document_section,
)


def _nodes(snapshot):
    return {node["id"]: node for node in snapshot["nodes"]}


@pytest.mark.parametrize(
    "roles,edges",
    [
        ((("triage", "分流"), ("free_tool", "自由工具")), (("triage", "free_tool"),)),
        ((("triage", "分流"), ("triage", "重复")), ()),
        (
            (("triage", "分流"), ("evidence", "证据")),
            (("triage", "evidence"), ("evidence", "triage")),
        ),
    ],
)
def test_workflow_plan_rejects_unknown_duplicate_and_cycle(roles, edges):
    with pytest.raises(ValueError):
        validate_workflow_plan("consultation", roles, edges)


def test_document_workflow_reports_real_checkpoint_and_specialist_executor():
    queued = document_workflow("queued", "queued", specialist_models_enabled=True)
    running = document_workflow("generating", "writer", specialist_models_enabled=True)
    failed = document_workflow("failed", "reviewer", specialist_models_enabled=True)
    assert queued["mode"] == "centralized"
    assert _nodes(queued)["coordinator"]["status"] == "queued"
    assert _nodes(running)["planner"]["status"] == "completed"
    assert _nodes(running)["planner"]["executor"] == "model"
    assert _nodes(running)["writer"]["status"] == "running"
    assert _nodes(failed)["reviewer"]["status"] == "failed"
    assert _nodes(document_workflow("completed", "delivery"))["planner"]["status"] == "skipped"


def test_consultation_workflow_keeps_fallback_and_review_separate():
    graph = {"retrieval_status": "empty"}
    safe = consultation_workflow(graph, safety_reply=True, phase="completed")
    assert _nodes(safe)["fallback"]["status"] == "completed"
    assert _nodes(safe)["writer"]["status"] == "skipped"
    live = consultation_workflow(graph, safety_reply=False, planner_status="completed")
    assert _nodes(live)["planner"]["executor"] == "model"
    assert _nodes(live)["writer"]["status"] == "running"
    assert "user_text" not in str(live)


async def test_consultation_planner_only_sends_redacted_question_and_fixed_style(monkeypatch):
    seen = {}

    async def fake_request(_model, _prompt, payload):
        seen.update(payload)
        return {"style": "brief"}

    monkeypatch.setattr(consultation_planner, "request_agent_json", fake_request)
    model = ModelConfig(
        id="qwen3.8-flash",
        name="test",
        provider="qwen",
        provider_name="test",
        description="test",
        base_url="https://example.test/v1",
        api_key=SecretStr("test"),
    )
    guidance = await consultation_planner.plan_consultation_answer(
        model, "我电话13800138000，想了解头痛。"
    )
    assert "13800138000" not in seen["question"]
    assert guidance == "保持简短，优先回答用户问的核心问题。"


async def test_evidence_reviewer_keeps_only_claims_with_locatable_source_quotes(monkeypatch):
    model = ModelConfig(
        id="qwen3.8-flash",
        name="test",
        provider="qwen",
        provider_name="test",
        description="test",
        base_url="https://example.test/v1",
        api_key=SecretStr("test"),
    )
    seen = {}

    async def fake_request(_model, _prompt, payload):
        seen.update(payload)
        return {"supported": [{"index": 0, "sourceId": 1, "quote": "有据段落"}]}

    monkeypatch.setattr(consultation_evidence_reviewer, "request_agent_json", fake_request)
    checked = await consultation_evidence_reviewer.check_answer_evidence(
        model,
        "有据段落[来源1]。\n\n无据段落。",
        [{"reference_number": 1, "title": "测试来源", "content": "有据段落"}],
    )
    assert checked == "有据段落[来源1]。"
    assert seen["sources"][0]["content"] == "有据段落"
    assert seen["claims"] == ["有据段落[来源1]。", "无据段落。"]


async def test_evidence_reviewer_rejects_a_fabricated_source_quote(monkeypatch):
    model = ModelConfig(
        id="qwen3.8-flash", name="test", provider="qwen", provider_name="test",
        description="test", base_url="https://example.test/v1", api_key=SecretStr("test"),
    )
    monkeypatch.setattr(
        consultation_evidence_reviewer,
        "request_agent_json",
        AsyncMock(return_value={"supported": [
            {"index": 0, "sourceId": 1, "quote": "来源中根本不存在"}
        ]}),
    )
    with pytest.raises(ValueError, match="quote absent"):
        await consultation_evidence_reviewer.check_answer_evidence(
            model,
            "药物一定有效。",
            [{"reference_number": 1, "title": "来源", "content": "疗效因人而异"}],
        )


async def test_evidence_reviewer_drops_unsupported_clause_in_same_paragraph(monkeypatch):
    model = ModelConfig(
        id="qwen3.8-flash", name="test", provider="qwen", provider_name="test",
        description="test", base_url="https://example.test/v1", api_key=SecretStr("test"),
    )
    monkeypatch.setattr(
        consultation_evidence_reviewer,
        "request_agent_json",
        AsyncMock(return_value={"supported": [
            {"index": 0, "sourceId": 1, "quote": "需要结合情况评估"}
        ]}),
    )
    checked = await consultation_evidence_reviewer.check_answer_evidence(
        model,
        "需要结合情况评估，保证治好。",
        [{"reference_number": 1, "title": "来源", "content": "需要结合情况评估"}],
    )
    assert "需要结合情况评估" in checked
    assert "保证治好" not in checked


async def test_evidence_reviewer_rejects_citation_for_another_source(monkeypatch):
    model = ModelConfig(
        id="qwen3.8-flash", name="test", provider="qwen", provider_name="test",
        description="test", base_url="https://example.test/v1", api_key=SecretStr("test"),
    )
    monkeypatch.setattr(
        consultation_evidence_reviewer,
        "request_agent_json",
        AsyncMock(return_value={"supported": [
            {"index": 0, "sourceId": 1, "quote": "需要结合情况评估"}
        ]}),
    )
    with pytest.raises(ValueError, match="citation does not match"):
        await consultation_evidence_reviewer.check_answer_evidence(
            model,
            "需要结合情况评估[来源2]。",
            [
                {"reference_number": 1, "title": "一", "content": "需要结合情况评估"},
                {"reference_number": 2, "title": "二", "content": "其他内容"},
            ],
        )


async def test_evidence_reviewer_refuses_when_no_claim_has_evidence(monkeypatch):
    model = ModelConfig(
        id="qwen3.8-flash", name="test", provider="qwen", provider_name="test",
        description="test", base_url="https://example.test/v1", api_key=SecretStr("test"),
    )
    monkeypatch.setattr(
        consultation_evidence_reviewer,
        "request_agent_json",
        AsyncMock(return_value={"supported": []}),
    )
    checked = await consultation_evidence_reviewer.check_answer_evidence(
        model,
        "保证治好。",
        [{"reference_number": 1, "title": "来源", "content": "需要进一步评估"}],
    )
    assert "保证治好" not in checked
    assert "未能通过证据核查" in checked


def test_evidence_reviewer_rejects_unreviewable_drafts():
    assert not consultation_evidence_reviewer.reviewable_answer("医学结论", [])
    assert not consultation_evidence_reviewer.reviewable_answer(
        "医学结论", [{"reference_number": index} for index in range(9)]
    )


def _citation() -> RetrievalCitation:
    return RetrievalCitation(
        chunk_id=uuid4(),
        document_id=uuid4(),
        source_key="test",
        organization="test",
        title="高血压科普",
        canonical_url="https://example.test/article",
        section_title="预防",
        version_label="test",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        content="高血压需要规范测量与医生评估。",
        similarity=0.9,
        trust_level="prototype",
    )


async def test_document_planner_and_reviewer_use_independent_bounded_model_calls():
    calls = []

    async def fake_request(system, payload):
        calls.append((system, payload))
        if len(calls) == 1:
            return {"headings": ["认识高血压", "何时就医"]}
        return {"risk": "uncertain"}

    outline = await plan_document_outline("高血压", [_citation()], requester=fake_request)
    plan = DocumentContentPlan.model_validate(
        {
            "title": "高血压科普",
            "audience": "普通成年人",
            "summary": "本资料介绍高血压基础知识，并提醒读者需要医生进一步评估。",
            "sections": [
                {"heading": "认识高血压", "paragraphs": ["需要规范测量。"], "sourceIds": [1]},
                {"heading": "何时就医", "bullets": ["建议医生评估。"], "sourceIds": [1]},
            ],
        }
    )
    review = await review_document_draft(plan, [_citation()], requester=fake_request)
    assert outline.headings == ["认识高血压", "何时就医"]
    assert review.risk == "uncertain"
    assert len(calls) == 2


async def test_document_revision_changes_one_section_once_without_new_sources():
    plan = DocumentContentPlan.model_validate(
        {
            "title": "高血压科普",
            "audience": "普通成年人",
            "summary": "本资料介绍高血压基础知识，并提醒读者需要医生进一步评估。",
            "sections": [
                {"heading": "认识高血压", "paragraphs": ["需要规范测量。"], "sourceIds": [1]},
                {
                    "heading": "何时就医",
                    "bullets": ["建议医生评估。", "没有来源的句子。"],
                    "sourceIds": [1],
                },
            ],
        }
    )
    calls = []

    async def fake_request(_prompt, payload):
        calls.append(payload)
        return {"heading": "何时就医", "bullets": ["建议医生评估。"], "sourceIds": [1]}

    revised = await revise_document_section(
        plan,
        [_citation()],
        DocumentReview(risk="uncertain", sectionIndex=1, issue="structure"),
        requester=fake_request,
    )
    assert len(calls) == 1
    assert revised.sections[0] == plan.sections[0]
    assert revised.sections[1].bullets == ["建议医生评估。"]
    assert plan.sections[1].bullets == ["建议医生评估。", "没有来源的句子。"]


async def test_document_revision_rejects_new_medical_text():
    plan = DocumentContentPlan.model_validate(
        {
            "title": "高血压科普",
            "audience": "普通成年人",
            "summary": "本资料介绍高血压基础知识，并提醒读者需要医生进一步评估。",
            "sections": [
                {"heading": "认识高血压", "paragraphs": ["需要规范测量。"], "sourceIds": [1]},
                {"heading": "何时就医", "bullets": ["建议医生评估。"], "sourceIds": [1]},
            ],
        }
    )

    async def fake_request(_prompt, _payload):
        return {"heading": "何时就医", "bullets": ["保证治好。"], "sourceIds": [1]}

    with pytest.raises(AppError) as exc:
        await revise_document_section(
            plan,
            [_citation()],
            DocumentReview(risk="uncertain", sectionIndex=1, issue="unsupported_claim"),
            requester=fake_request,
        )
    assert exc.value.code == "DOCUMENT_AGENT_REVISION_INVALID"


async def test_document_create_persists_opt_in_and_exposes_workflow(profile_context, monkeypatch):
    client, _, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "multi_agent_enabled", True)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    conversation = await client.post(
        "/api/v1/consultations", json={"clientRequestId": str(uuid4())}
    )
    cid = conversation.json()["id"]
    message = await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={"clientRequestId": str(uuid4()), "content": "帮我生成一份高血压预防 Word 科普文档"},
    )
    response = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": message.json()["id"],
            "noticeAccepted": True,
            "noticeVersion": "document-generation-v1",
        },
    )
    assert response.status_code == 202
    assert response.json()["workflow"]["scene"] == "document_generation"
    assert _nodes(response.json()["workflow"])["planner"]["executor"] == "model"


async def test_document_p1_attempt_budget_blocks_another_model_run(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "multi_agent_enabled", True)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    conversation = await client.post(
        "/api/v1/consultations", json={"clientRequestId": str(uuid4())}
    )
    cid = conversation.json()["id"]
    message = await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={"clientRequestId": str(uuid4()), "content": "生成高血压科普 Word 文档"},
    )
    created = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": message.json()["id"],
            "noticeAccepted": True,
            "noticeVersion": "document-generation-v1",
        },
    )
    generation_id = UUID(created.json()["id"])
    row = await db.get(GeneratedDocument, generation_id)
    row.attempt_count = 2
    await db.commit()
    called = AsyncMock()
    monkeypatch.setattr(generation_service, "plan_document_outline", called)
    assert not await generation_service.process_one(db, generation_id)
    called.assert_not_awaited()
    result = await client.get(f"/api/v1/document-generations/{generation_id}")
    assert result.json()["errorCode"] == "DOCUMENT_AGENT_RETRY_LIMIT"


@pytest.mark.parametrize("review_risk", ["none", "uncertain"])
async def test_document_worker_runs_planner_writer_reviewer_and_delivery(
    profile_context, monkeypatch, tmp_path, review_risk
):
    client, db, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "multi_agent_enabled", True)
    monkeypatch.setattr(get_settings(), "document_generation_storage_dir", str(tmp_path))
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    consultation = await client.post(
        "/api/v1/consultations", json={"clientRequestId": str(uuid4())}
    )
    cid = consultation.json()["id"]
    message = await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={"clientRequestId": str(uuid4()), "content": "帮我生成一份高血压预防 Word 科普文档"},
    )
    created = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": message.json()["id"],
            "noticeAccepted": True,
            "noticeVersion": "document-generation-v1",
        },
    )
    generation_id = UUID(created.json()["id"])
    calls = []

    async def fake_search(_db, _topic, **_kwargs):
        return RetrievalResult(
            query_redacted=False, model="test", version="test", items=[_citation()]
        )

    async def fake_outline(_topic, _citations):
        calls.append("planner")
        return DocumentOutline(headings=["认识高血压", "何时就医"])

    async def fake_writer(_topic, _citations, *, outline):
        assert outline.headings[0] == "认识高血压"
        calls.append("writer")
        return DocumentContentPlan.model_validate(
            {
                "title": "高血压科普",
                "audience": "普通成年人",
                "summary": "本资料介绍高血压基础知识，并提醒读者需要医生进一步评估。",
                "sections": [
                    {"heading": "认识高血压", "paragraphs": ["需要规范测量。"], "sourceIds": [1]},
                    {"heading": "何时就医", "bullets": ["建议医生评估。"], "sourceIds": [1]},
                ],
            }
        )

    async def fake_reviewer(_plan, _citations):
        calls.append("reviewer")
        if review_risk == "uncertain":
            return DocumentReview(risk="uncertain", sectionIndex=1, issue="unsupported_claim")
        return DocumentReview(risk="none")

    async def fake_revision(plan, _citations, _verdict):
        calls.append("revision")
        return plan

    monkeypatch.setattr(generation_service, "search_knowledge", fake_search)
    monkeypatch.setattr(generation_service, "plan_document_outline", fake_outline)
    monkeypatch.setattr(generation_service, "generate_content_plan", fake_writer)
    monkeypatch.setattr(generation_service, "review_document_draft", fake_reviewer)
    monkeypatch.setattr(generation_service, "revise_document_section", fake_revision)
    assert await generation_service.process_one(db, generation_id)
    expected = ["planner", "writer", "reviewer"]
    if review_risk == "uncertain":
        expected.append("revision")
    assert calls == expected
    result = await client.get(f"/api/v1/document-generations/{generation_id}")
    assert result.json()["status"] == "completed"
    assert all(node["status"] == "completed" for node in result.json()["workflow"]["nodes"])


async def test_consultation_stream_runs_optional_planner_and_exposes_workflow(
    profile_context, monkeypatch
):
    client, _, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "multi_agent_enabled", True)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = await client.post(
        "/api/v1/consultations", json={"clientRequestId": str(uuid4())}
    )
    cid = created.json()["id"]
    await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={"clientRequestId": str(uuid4()), "content": "你好"},
    )
    model = ModelConfig(
        id="qwen3.8-flash",
        name="test",
        provider="qwen",
        provider_name="test",
        description="test",
        base_url="https://example.test/v1",
        api_key=SecretStr("test"),
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

    planner = AsyncMock(return_value="保持简短，优先回答用户问的核心问题。")
    monkeypatch.setattr("app.api.routes.consultations.run_consultation_generation", fake_graph)
    monkeypatch.setattr("app.api.routes.consultations.plan_consultation_answer", planner)

    async def fake_stream(history, *_args):
        assert any("回答组织建议" in item["content"] for item in history)
        yield "你好，我可以帮助你了解健康科普问题。"

    monkeypatch.setattr("app.ai.provider.stream_chat", fake_stream)
    response = await client.post(
        f"/api/v1/consultations/{cid}/stream",
        json={"clientRequestId": str(uuid4()), "modelId": model.id},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert planner.await_count == 1
    assert _nodes(events[0]["workflow"])["planner"]["status"] == "completed"
    assert events[-1]["type"] == "done"
    assert _nodes(events[-1]["workflow"])["reviewer"]["status"] == "completed"


@pytest.mark.parametrize(
    ("multi_agent", "answer_format", "review_fails", "private_source"),
    [(True, "plain", False, False), (False, "plain", False, False),
     (False, "card", False, False), (False, "plain", True, False),
     (False, "plain", False, True)],
)
async def test_consultation_p1_checks_evidence_before_exposing_delta(
    profile_context, monkeypatch, multi_agent, answer_format, review_fails, private_source
):
    client, _, (user, _) = profile_context
    monkeypatch.setattr(get_settings(), "multi_agent_enabled", multi_agent)
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id))
    created = await client.post("/api/v1/consultations", json={"clientRequestId": str(uuid4())})
    cid = created.json()["id"]
    await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={"clientRequestId": str(uuid4()), "content": "头痛是什么"},
    )
    model = ModelConfig(
        id="qwen3.8-flash",
        name="test",
        provider="qwen",
        provider_name="test",
        description="test",
        base_url="https://example.test/v1",
        api_key=SecretStr("test"),
    )
    monkeypatch.setattr(
        "app.api.routes.consultations.get_model_for_user", AsyncMock(return_value=model)
    )
    if private_source:
        monkeypatch.setattr(
            "app.api.routes.consultations.build_private_knowledge_context",
            AsyncMock(return_value=("私人资料片段", [{
                "reference_number": 1, "document_name": "用户选择的文件",
                "content": "头痛记录", "collection_id": uuid4(),
                "collection_name": "测试", "document_id": uuid4(),
                "locator": "1", "similarity": 0.9,
            }])),
        )
    evidence = {
        "source_key": "test",
        "organization": "test",
        "title": "头痛资料",
        "canonical_url": "https://example.test/headache",
        "section_title": "症状",
        "content": "头痛需要结合具体情况评估。",
        "similarity": 0.9,
        "trust_level": "prototype",
    }

    async def fake_graph(_text, _db):
        return {
            "triage_route": "continue",
            "retrieval_status": "completed",
            "retrieval_items": [evidence],
            "retrieval_error_code": None,
            "retrieval_intent": True,
            "retrieval_gate_reason": "medical_content",
            "web_search_status": "skipped",
            "web_search_error_code": None,
        }

    async def fake_stream(*_args):
        yield "需要结合情况评估[来源1]。\n\n"
        yield "保证治好。"

    checker = (
        AsyncMock(side_effect=RuntimeError("review unavailable"))
        if review_fails
        else AsyncMock(return_value="需要结合情况评估[来源1]。")
    )
    monkeypatch.setattr("app.api.routes.consultations.run_consultation_generation", fake_graph)
    monkeypatch.setattr(
        "app.api.routes.consultations.plan_consultation_answer", AsyncMock(return_value="")
    )
    monkeypatch.setattr("app.api.routes.consultations.check_answer_evidence", checker)
    monkeypatch.setattr("app.ai.provider.stream_chat", fake_stream)
    response = await client.post(
        f"/api/v1/consultations/{cid}/stream",
        json={"clientRequestId": str(uuid4()), "modelId": model.id,
              "answerFormat": answer_format},
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["start", "delta", "done"]
    if review_fails:
        assert "未能完成证据核查" in events[1]["content"]
    else:
        assert events[1]["content"] == "需要结合情况评估[来源1]。"
    assert "保证治好" not in response.text
    assert checker.await_count == 1
    if private_source:
        assert any(item["reference_number"] == "P1" for item in checker.call_args.args[2])
    assert _nodes(events[-1]["workflow"])["evidence_reviewer"]["status"] == (
        "failed" if review_fails else "completed"
    )
