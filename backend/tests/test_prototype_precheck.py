"""机器预审规则的单测：证明它只筛「明显越界」，且不产出「通过」结论。"""

from app.rag.prototype_precheck import (
    PRECHECK_RULES,
    PrecheckResult,
    has_escalation,
    scan_text,
)


def test_scan_flags_obvious_dosage_and_drug_name() -> None:
    text = "孩子发烧可以吃布洛芬 5 毫克每公斤，疗程三天。"
    rules = {finding.rule for finding in scan_text(text)}
    assert "dosage" in rules
    assert "drug_name" in rules
    assert "regimen" in rules


def test_scan_flags_diagnosis_tone_and_efficacy_claim() -> None:
    rules = {finding.rule for finding in scan_text("你就是肺炎，吃这个能治好。")}
    assert "diagnosis_tone" in rules
    assert "efficacy_claim" in rules


def test_scan_flags_personal_exercise_prescription() -> None:
    rules = {finding.rule for finding in scan_text("您把心率控制到 140，每天 30 分钟。")}
    assert "personal_prescription" in rules


def test_plain_health_science_text_is_not_flagged() -> None:
    text = "发热是人体对感染的正常反应，多数情况可自行缓解；若持续高热或出现呼吸困难，应及时就医。"
    assert scan_text(text) == []
    assert has_escalation(text) is True


def test_escalation_detection() -> None:
    assert has_escalation("出现抽搐要立刻去医院") is True
    assert has_escalation("多喝热水就好") is False


def test_result_note_never_promises_approval() -> None:
    # 机器预审的结论只能是「疑似，待人工确认」，不得出现「通过」这类判定。
    note = PrecheckResult().note
    assert "疑似" in note
    assert "不判定医学正确性" in note


def test_rule_table_is_locatable() -> None:
    # 每条规则都要有可读标签，人工才可能据此解释该删该改。
    assert PRECHECK_RULES
    for rule, label, _pattern in PRECHECK_RULES:
        assert rule and label