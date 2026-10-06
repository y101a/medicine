"""稿件-来源确定性比对的单测：用「考试卷」三段样文当固定判分基准。

判分口径（与人工验收一致）：
- 正确稿应报 0 条；
- 边界稿应报「食盐那句无来源」等 A 类；
- 高危稿必须命中 B 类 6 条 + A 类（无来源/情态升级/限定丢失）。
本模块不依赖任何模型，结果必须可复现。
"""

from app.rag.draft_source_check import compare_draft

GOOD_DRAFT = (
    "发热是人体对感染的常见反应，多数可自行缓解。"
    "出现持续高热、呼吸困难或意识改变时，应及时就医。"
    "本文不提供诊断或用药建议，具体请咨询医生。"
)
GOOD_SOURCE = (
    "发热是人体对感染的常见反应，多数可自行缓解。"
    "出现持续高热、呼吸困难或意识改变时，应及时就医。"
)

BORDER_DRAFT = (
    "孩子发烧不要捂汗，捂汗可能导致体温过高。"
    "不要自行服用退烧药，也不要因为症状好转就停药。"
    "发烧时如出现精神差、抽搐，应及时就医。"
    "食盐每天不超过 5 克。"
)
BORDER_SOURCE = (
    "儿童体温调节中枢不完善，捂汗可能导致体温过高。"
    "用药请遵医务人员说明。出现精神差、抽搐应及时就医。"
)

BAD_DRAFT = (
    "你只要每天跑步，心率保持在每分钟150次，就一定能根治高血压。"
    "如果跑步后头晕，说明你就是高血压。"
    "再服用「示例药A」，每次2片，连续7天；感觉好转就停药。"
)
BAD_SOURCE = (
    "对没有运动禁忌的成年人，可根据自身情况考虑适量活动。"
    "活动中如出现头晕等不适，应停止活动并及时就医。"
    "本文不提供疾病诊断或药物使用建议。"
)


def test_good_draft_reports_nothing() -> None:
    result = compare_draft(GOOD_DRAFT, GOOD_SOURCE)
    assert result.unsourced == []
    assert result.modal_upgrades == []
    assert result.dropped_qualifiers == []
    assert result.boundary_findings == []
    assert result.missing_escalation is False


def test_border_draft_flags_unsourced_sentence() -> None:
    result = compare_draft(BORDER_DRAFT, BORDER_SOURCE)
    flagged = " ".join(str(item["sentence"]) for item in result.unsourced)
    assert "食盐" in flagged


def test_border_draft_keeps_safety_sentences_quiet() -> None:
    # 「不要因为症状好转就停药」是劝阻，B 类不得报出。
    result = compare_draft(BORDER_DRAFT, BORDER_SOURCE)
    rules = {str(item["rule"]) for item in result.boundary_findings}
    assert "regimen" not in rules


def test_bad_draft_hits_boundary_rules() -> None:
    result = compare_draft(BAD_DRAFT, BAD_SOURCE)
    rules = {str(item["rule"]) for item in result.boundary_findings}
    for expected in ("dosage", "regimen", "drug_name", "diagnosis_tone", "efficacy_claim"):
        assert expected in rules, expected


def test_bad_draft_flags_unsourced_and_modal_and_qualifier() -> None:
    result = compare_draft(BAD_DRAFT, BAD_SOURCE)
    assert result.unsourced, "心率/根治那句在来源里找不到对应"
    assert result.modal_upgrades, "来源「可…考虑」被写成「只要…就一定」"
    assert result.dropped_qualifiers, "来源「没有运动禁忌的成年人」被丢掉"


def test_missing_escalation_is_reported() -> None:
    assert compare_draft(BAD_DRAFT, BAD_SOURCE).missing_escalation is True
    assert compare_draft(GOOD_DRAFT, GOOD_SOURCE).missing_escalation is False


def test_note_never_promises_approval() -> None:
    note = compare_draft(GOOD_DRAFT, GOOD_SOURCE).note
    assert "疑似" in note
    assert "不出「通过」" in note


def test_idempotent_across_runs() -> None:
    # 稳定性是这套方案存在的理由：模型会随机拒答，本地比对必须每次一致。
    first = compare_draft(BAD_DRAFT, BAD_SOURCE)
    second = compare_draft(BAD_DRAFT, BAD_SOURCE)
    assert first == second