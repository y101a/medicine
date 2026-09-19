"""Pure-logic tests for health record extraction; no database required."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.health_context import render_health_context
from app.ai.health_extract import build_extraction_prompt, parse_extraction
from app.core.errors import AppError
from app.models.health_record import HealthRecordCategory, HealthRecordSource
from app.schemas.health_records import (
    HealthRecordCreate,
    HealthRecordOut,
    HealthRecordSettingsUpdate,
    HealthRecordUpdate,
)
from app.services.health_records import content_hash


def fact_payload(category: str, content: str) -> str:
    return json.dumps({"facts": [{"category": category, "content": content}]}, ensure_ascii=False)


def test_parse_extraction_accepts_plain_json():
    facts = parse_extraction(fact_payload("symptom", "最近一周夜间失眠"))
    assert len(facts) == 1
    assert facts[0].category == HealthRecordCategory.SYMPTOM
    assert facts[0].content == "最近一周夜间失眠"


def test_parse_extraction_reads_fenced_and_prose_wrapped_json():
    raw = (
        "好的，结果如下：\n"
        '```json\n{"facts":[{"category":"allergy","content":"对青霉素过敏"}]}\n```'
    )
    assert [item.content for item in parse_extraction(raw)] == ["对青霉素过敏"]


def test_parse_extraction_accepts_empty_fact_list():
    assert parse_extraction('{"facts":[]}') == []


@pytest.mark.parametrize(
    "content",
    [
        "可能患有糖尿病",
        "疑似甲状腺功能异常",
        "建议尽快就医",
        "不排除贫血",
        "考虑为慢性胃炎",
        "倾向于焦虑状态",
    ],
)
def test_inference_sentences_are_never_stored(content):
    assert parse_extraction(fact_payload("symptom", content)) == []


@pytest.mark.parametrize(
    "content",
    ["13800138000", "11010519491231002X", "someone@example.com"],
)
def test_identity_data_is_never_stored(content):
    assert parse_extraction(fact_payload("other", content)) == []


def test_malformed_output_raises_app_error():
    with pytest.raises(AppError) as error:
        parse_extraction("抱歉，我无法完成这个任务")
    assert error.value.code == "HEALTH_EXTRACT_INVALID"


def test_unknown_category_is_rejected():
    with pytest.raises(AppError) as error:
        parse_extraction(fact_payload("diagnosis", "高血压"))
    assert error.value.code == "HEALTH_EXTRACT_INVALID"


def test_more_than_five_facts_are_rejected():
    raw = json.dumps(
        {"facts": [{"category": "symptom", "content": f"记录条目{i}"} for i in range(6)]},
        ensure_ascii=False,
    )
    with pytest.raises(AppError):
        parse_extraction(raw)


def test_prompt_carries_categories_and_existing_facts():
    prompt = build_extraction_prompt("我最近总口渴", ["长期高血压（用户自述）"])
    assert "general_status" in prompt
    assert "symptom" in prompt
    assert "长期高血压（用户自述）" in prompt
    assert "我最近总口渴" in prompt
    assert "绝不能记录" in prompt


def test_prompt_truncates_overlong_message():
    prompt = build_extraction_prompt("啊" * 5000)
    assert "啊" * 1200 in prompt
    assert "啊" * 1201 not in prompt


def test_prompt_redacts_direct_identifiers_before_provider_call():
    prompt = build_extraction_prompt(
        "我叫张三，手机号13800138000，身份证11010519491231002X，最近总口渴",
        ["联系邮箱 test@example.com"],
    )

    assert "张三" not in prompt
    assert "13800138000" not in prompt
    assert "11010519491231002X" not in prompt
    assert "test@example.com" not in prompt
    assert "总口渴" in prompt


def test_health_context_block_states_the_safety_boundaries():
    block = render_health_context('[{"category":"近期症状","content":"夜间失眠"}]')
    assert "夜间失眠" in block
    assert "不得据记录推断病因" in block
    assert "不得因为记录中存在某项情况而降低对红旗症状的警惕" in block
    assert "以本次描述为准" in block


def test_content_hash_normalizes_width_and_case():
    assert content_hash(" 高血压 ") == content_hash("高血压")
    assert content_hash("ABC") == content_hash("abc")
    assert content_hash("Ａ") == content_hash("A")
    assert content_hash("高血压") != content_hash("低血压")


@pytest.mark.parametrize(
    "payload",
    [{}, {"collectionEnabled": None}, {"noticeSeen": None}],
    ids=["empty", "null-enabled", "null-notice"],
)
def test_settings_update_rejects_empty_or_null(payload):
    with pytest.raises(ValidationError):
        HealthRecordSettingsUpdate.model_validate(payload)


def test_settings_update_takes_camel_case_aliases():
    payload = HealthRecordSettingsUpdate.model_validate(
        {"collectionEnabled": False, "noticeSeen": True}
    )
    assert payload.collection_enabled is False
    assert payload.notice_seen is True


def test_settings_update_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        HealthRecordSettingsUpdate.model_validate({"collection_enabled": False})


def test_record_create_trims_text_and_bounds_length():
    created = HealthRecordCreate.model_validate({"category": "symptom", "content": "  夜间失眠  "})
    assert created.content == "夜间失眠"
    with pytest.raises(ValidationError):
        HealthRecordCreate.model_validate({"category": "symptom", "content": "   "})
    with pytest.raises(ValidationError):
        HealthRecordCreate.model_validate({"category": "symptom", "content": "啊" * 501})


def test_record_update_requires_a_real_change():
    with pytest.raises(ValidationError):
        HealthRecordUpdate.model_validate({})
    with pytest.raises(ValidationError):
        HealthRecordUpdate.model_validate({"content": None})
    assert HealthRecordUpdate.model_validate({"content": " 夜间失眠 "}).content == "夜间失眠"


def test_record_output_uses_camel_case_contract():
    now = datetime.now(UTC)
    dumped = HealthRecordOut(
        id=uuid4(),
        category=HealthRecordCategory.SYMPTOM,
        category_label="近期症状",
        content="夜间失眠",
        source=HealthRecordSource.CONVERSATION,
        recorded_at=now,
        updated_at=now,
    ).model_dump(by_alias=True)
    assert set(dumped) == {
        "id",
        "category",
        "categoryLabel",
        "content",
        "source",
        "recordedAt",
        "updatedAt",
    }
    assert dumped["categoryLabel"] == "近期症状"
    assert dumped["category"] == "symptom"
