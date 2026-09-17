from app.safety.triage import TRIAGE_RULESET_VERSION, assess_red_flags, evaluate_triage


def test_emergency_red_flags_are_detected_without_a_model():
    cases = {
        "家人突然昏迷，怎么也叫不醒": "altered_consciousness",
        "现在喘不上气，感觉无法呼吸": "severe_breathing_problem",
        "胸口突然很痛，还有压迫感": "acute_chest_pain",
        "刚才突然全身抽搐": "seizure",
        "伤口一直血流不止": "severe_bleeding",
        "突然口角歪斜，说话含糊不清": "stroke_warning",
        "疑似一氧化碳中毒": "life_threatening_exposure",
        "严重过敏后嘴唇肿，而且吞咽困难": "severe_allergic_reaction",
    }
    for content, rule_id in cases.items():
        result = assess_red_flags(content)
        assert result is not None, content
        assert result.level == "emergency"
        assert rule_id in result.rule_ids


def test_negated_historical_and_resolved_symptoms_do_not_trigger():
    cases = (
        "我没有胸痛，也没有呼吸困难",
        "否认抽搐和意识不清",
        "以前有过胸痛，现在没有不适",
        "胸痛已经缓解，想了解日常注意事项",
        "没有口角歪斜，讲话也很清楚",
    )
    for content in cases:
        assert assess_red_flags(content) is None, content


def test_enhanced_red_flags_are_detected():
    cases = {
        "患者心脏骤停，没有正常呼吸": "cardiorespiratory_arrest",
        "家人刚从高处摔下，头部重伤": "severe_trauma",
        "突然雷击样头痛，从来没有这么严重": "sudden_severe_headache",
        "孕妇现在大量出血": "pregnancy_emergency",
        "我准备跳楼，控制不住自己": "imminent_self_harm",
        "老人突然走不稳，而且一侧手脚麻木": "stroke_warning",
    }
    for content, rule_id in cases.items():
        result = assess_red_flags(content)
        assert result is not None, content
        assert rule_id in result.rule_ids
        assert result.rule_version == TRIAGE_RULESET_VERSION
        assert result.assessment_method == "deterministic_rules"


def test_educational_or_hypothetical_questions_do_not_trigger():
    cases = (
        "什么是胸痛？",
        "我想了解呼吸困难有哪些常见原因",
        "请科普一下抽搐和癫痫大发作的区别",
        "如果出现口角歪斜应该怎么办",
        "如何识别严重过敏",
    )
    for content in cases:
        assert assess_red_flags(content) is None, content


def test_langgraph_state_has_stable_route_without_raw_text():
    safe = evaluate_triage("我想了解什么是胸痛").as_langgraph_state()
    assert safe == {
        "triage_route": "continue",
        "triage_rule_version": TRIAGE_RULESET_VERSION,
        "triage_rule_ids": [],
        "triage_result": None,
    }

    emergency = evaluate_triage("现在喘不上气").as_langgraph_state()
    assert emergency["triage_route"] == "emergency"
    assert emergency["triage_rule_ids"] == ["severe_breathing_problem"]
    assert "喘不上气" not in str(emergency)
