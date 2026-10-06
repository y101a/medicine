"""机器预审规则的单测。

覆盖两类事实：
1. 真违规必须命中（含一段人工构造的高危样文，覆盖剂量/药名/疗程/确诊口气/疗效承诺/个人强度目标）。
2. 上一版在真实语料上产生的误报必须被上下文抑制（否定安全句、膳食限量、非用药的「减量」、免责声明、被否定的绝对化）。
并且：机器只在本地做匹配与定位，不生成医学结论，也不出「通过」。
"""

from app.rag.prototype_precheck import (
    PRECHECK_RULES,
    PrecheckResult,
    has_escalation,
    scan_text,
    scan_text_with_suppression,
)

# 人工构造的高危样文：每句都对应一条规则。
BAD_TEXT = (
    "你只要每天跑步，心率保持在每分钟150次，就一定能根治高血压。"
    "如果跑步后头晕，说明你就是高血压。"
    "再服用「示例药A」，每次2片，连续7天；感觉好转就停药。"
)


def test_bad_text_hits_every_expected_rule() -> None:
    rules = {finding.rule for finding in scan_text(BAD_TEXT)}
    assert "personal_prescription" in rules  # 心率保持在每分钟150次
    assert "efficacy_claim" in rules  # 一定能根治
    assert "diagnosis_tone" in rules  # 说明你就是高血压
    assert "drug_name" in rules  # 服用「示例药A」
    assert "dosage" in rules  # 每次2片
    assert "regimen" in rules  # 连续7天 / 就停药


def test_bad_text_has_no_escalation_sentence() -> None:
    assert has_escalation(BAD_TEXT) is False


def test_safety_negation_is_suppressed() -> None:
    for text in (
        "不能因为一次血压正常就自行停药。",
        "已在服药者不要因一次读数正常就自行停药。",
        "不要擅自加量、减量、停药。",
        "切勿自行买药。",
    ):
        assert scan_text(text) == [], text


def test_disclaimer_sentence_is_suppressed() -> None:
    text = "本文不给出个人自用的中药浴足配方与「疗程」。"
    assert scan_text(text) == []
    assert scan_text_with_suppression(text)[0].suppression_reason == "disclaimer"


def test_dietary_and_physiological_limits_are_suppressed() -> None:
    for text in (
        "成年人每天摄入食盐不超过5克，烹调油25~30克。",
        "运动前30分钟饮水200~300毫升，运动中每15~20分钟补水100~150毫升。",
        "成年人如饮酒，一天饮用的酒精量不超过15克。",
    ):
        assert scan_text(text) == [], text


def test_exercise_volume_is_not_treated_as_medication() -> None:
    text = "出现大汗淋漓、明显肌肉疲劳，提示运动量已偏大，应停止或减量。"
    assert scan_text(text) == []
    findings = scan_text_with_suppression(text)
    assert findings and findings[0].suppression_reason == "non_medication_context"


def test_negated_absolute_is_suppressed() -> None:
    text = "胸口憋闷或者疼痛，我们叫心绞痛，心绞痛不一定是疼。"
    assert scan_text(text) == []


def test_efficacy_claim_is_never_suppressed() -> None:
    # 疗效承诺不做上下文抑制：哪怕句子里另有否定词，也要报出来交人工判断。
    rules = {finding.rule for finding in scan_text("不能说某种药能根治高血压。")}
    assert "efficacy_claim" in rules


def test_plain_health_science_text_is_not_flagged() -> None:
    text = "发热是人体对感染的正常反应，多数情况可自行缓解；若持续高热或出现呼吸困难，应及时就医。"
    assert scan_text(text) == []
    assert has_escalation(text) is True


def test_escalation_detection() -> None:
    assert has_escalation("出现抽搐要立刻去医院") is True
    assert has_escalation("多喝热水就好") is False


def test_result_note_never_promises_approval() -> None:
    note = PrecheckResult().note
    assert "疑似" in note
    assert "不判定医学正确性" in note


def test_rule_table_is_locatable() -> None:
    assert PRECHECK_RULES
    for rule, label, _pattern in PRECHECK_RULES:
        assert rule and label