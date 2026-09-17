"""Lock the invariant that health records can never influence red-flag triage.

健康记录只能用于减少重复询问、贴合科普与提醒就医，不能改变紧急分流的判断。
这组测试让该不变量在结构上和行为上都可回归验证。
"""

import inspect

from app.ai.graph.workflow import run_consultation_safety
from app.safety import triage


def test_safety_graph_only_receives_the_current_message():
    """签名里没有 db / user / 记录参数，安全预检结构上读不到健康记录。"""

    assert list(inspect.signature(run_consultation_safety).parameters) == ["user_text"]


def test_triage_entry_points_have_no_user_or_record_parameter():
    for name in ("assess_red_flags", "evaluate_triage"):
        parameters = inspect.signature(getattr(triage, name)).parameters
        assert list(parameters) == ["content", "assessed_at"], name


def test_triage_module_never_references_health_records():
    assert "health_record" not in inspect.getsource(triage).lower()


def test_self_reported_history_does_not_suppress_red_flag_escalation():
    """即使用户先说自己有慢性病史并控制良好，红旗仍必须原样升级。"""

    bare = triage.assess_red_flags("突然胸痛，呼吸困难")
    with_history = triage.assess_red_flags(
        "我有高血压病史，一直控制得很好，现在突然胸痛，呼吸困难"
    )

    assert bare is not None
    assert with_history is not None
    assert bare.level == "emergency"
    assert with_history.level == "emergency"
    assert with_history.rule_ids == bare.rule_ids


def test_benign_message_is_not_escalated():
    assert triage.assess_red_flags("最近有点累") is None