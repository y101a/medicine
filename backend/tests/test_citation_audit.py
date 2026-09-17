import json
from types import SimpleNamespace
from uuid import uuid4

from app.api.routes import consultations as route
from app.rag.citation_audit import audit_answer_citations
from app.schemas.consultations import MessageCitation


def sample_sources():
    return [
        {"reference_number": 1, "canonical_url": "https://example.org/a"},
        {"reference_number": 2, "canonical_url": "https://example.org/a"},
        {"reference_number": 3, "canonical_url": "https://example.org/b"},
    ]


def test_only_referenced_chunks_are_kept_even_when_document_url_repeats():
    checked, cited = audit_answer_citations(
        "有资料[来源3]、[来源2]，再次引用[来源2]。", sample_sources()
    )
    assert checked == "有资料[来源3]、[来源2]，再次引用[来源2]。"
    assert [item["reference_number"] for item in cited] == [2, 3]


def test_fabricated_source_is_marked_and_never_credited():
    checked, cited = audit_answer_citations(
        "有记录[来源1]，另有说法[来源99]。", sample_sources()
    )
    assert "[来源1]" in checked
    assert "[来源99]" not in checked
    assert "[引用未核实]" in checked
    assert "不能视为有资料支持" in checked
    assert [item["reference_number"] for item in cited] == [1]


def test_retrieval_without_answer_citation_does_not_claim_source():
    checked, cited = audit_answer_citations("这是普通科普。", sample_sources())
    assert cited == []
    assert checked == "这是普通科普。"


def test_unnumbered_source_claim_is_flagged_when_evidence_was_available():
    checked, cited = audit_answer_citations(
        "根据检索资料，这种情况比较常见。", sample_sources()
    )
    assert cited == []
    assert "未标注可核验的来源编号" in checked
    assert "不能视为已有资料支持" in checked


def test_common_source_bracket_variants_are_normalized_and_verified():
    checked, cited = audit_answer_citations(
        "资料见【来源 1】和[来源 2]。", sample_sources()
    )
    assert checked == "资料见[来源1]和[来源2]。"
    assert [item["reference_number"] for item in cited] == [1, 2]


def test_no_retrieval_and_fabricated_citation_is_not_supported():
    checked, cited = audit_answer_citations("详情见[来源1]。", [])
    assert cited == []
    assert "[引用未核实]" in checked


def test_oversized_or_zero_padded_number_cannot_crash_or_claim_evidence():
    content = "伪引用[来源" + "9" * 5000 + "]，以及[来源01]。"
    checked, cited = audit_answer_citations(content, sample_sources())
    assert cited == []
    assert checked.count("[引用未核实]") == 2


def test_no_retrieval_and_no_marker_keeps_chat_unchanged():
    assert audit_answer_citations("你好。", []) == ("你好。", [])


def test_legacy_source_without_reference_number_can_still_be_restored():
    old_source = {
        "source_key": "test", "organization": "测试机构", "title": "健康资料",
        "canonical_url": "https://example.org/medical", "section_title": None,
        "similarity": 0.8, "trust_level": "approved",
    }
    citation = MessageCitation.model_validate(old_source)
    assert citation.reference_number is None
    assert citation.model_dump(by_alias=True)["referenceNumber"] is None


async def test_stream_final_message_saves_only_real_references_without_database(monkeypatch):
    evidence = {
        "source_key": "prototype", "organization": "测试机构", "title": "头痛科普",
        "canonical_url": "https://example.org/medical", "section_title": "症状",
        "similarity": 0.8, "trust_level": "prototype", "content": "测试资料",
    }

    async def no_triage(*_args):
        return None

    async def history(*_args):
        return [{"role": "user", "content": "头痛是什么"}], None

    async def context(*_args):
        return {
            "triage_route": "continue", "retrieval_items": [evidence],
            "retrieval_status": "completed", "retrieval_gate_reason": "medical_content",
            "web_search_status": "skipped", "web_search_error_code": None,
            "retrieval_error_code": None,
        }

    async def chunks(*_args):
        yield "常见问题[来源1]，另一个说法[来源8]。"

    async def save(*args, **kwargs):
        return SimpleNamespace(
            model_dump=lambda **_opts: {
                "content": args[4], "citations": kwargs["citations"],
            }
        )

    async def commit():
        return None

    monkeypatch.setattr(route.service, "pending_triage", no_triage)
    monkeypatch.setattr(route.service, "ai_history", history)
    monkeypatch.setattr(route.service, "append_assistant_message", save)

    async def no_health_context(*_args):
        return None

    # 本用例刻意不使用数据库，健康记录上下文必须被桩掉。
    monkeypatch.setattr(route.health_service, "build_health_context", no_health_context)
    monkeypatch.setattr(route, "run_consultation_generation", context)
    monkeypatch.setattr(route, "get_model", lambda *_: SimpleNamespace(
        id="test", name="隔离模型", provider="test",
    ))
    monkeypatch.setattr(route.provider, "stream_chat", chunks)
    response = await route.stream_answer(
        uuid4(), SimpleNamespace(model_id="test", answer_format="plain",
                                 client_request_id=uuid4()),
        SimpleNamespace(id=uuid4()), SimpleNamespace(commit=commit),
    )
    events = [json.loads(line) async for line in response.body_iterator]
    assert [event["type"] for event in events] == ["start", "delta", "done"]
    assert "[来源8]" not in events[-1]["message"]["content"]
    assert "[引用未核实]" in events[-1]["message"]["content"]
    assert [source["reference_number"] for source in events[-1]["message"]["citations"]] == [1]
