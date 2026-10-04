from app.ai.no_evidence import SAFETY_NOTICE, no_evidence_reply, unverified_web_risk_reply


def test_unverified_web_only_blocks_high_risk_but_allows_general_explanation():
    retrieval = {"retrieval_items": [{
        "source_key": "web_search_prototype",
        "organization": "未核实网站（rare-medical.org）",
    }]}
    assert unverified_web_risk_reply("法布雷病是什么，有哪些常见表现", retrieval) is None
    assert "不能据此给出个人诊断" in unverified_web_risk_reply(
        "法布雷病怎么治，药吃多少", retrieval
    )
    assert unverified_web_risk_reply(
        "法布雷病怎么治", retrieval, has_user_document=True
    ) is None
    assert unverified_web_risk_reply("法布雷病怎么治", {
        "retrieval_items": [*retrieval["retrieval_items"], {
            "source_key": "public_medical_knowledge", "organization": "医院",
        }],
    }) is None


def result(*, local="empty", web="skipped", items=None):
    return {
        "retrieval_gate_reason": "medical_content",
        "retrieval_status": local,
        "retrieval_items": [] if items is None else items,
        "web_search_status": web,
    }


def test_named_disease_without_evidence_gets_deterministic_uncertainty():
    answer = no_evidence_reply("法布雷病是什么？有哪些常见表现？", result())
    assert answer is not None
    assert "法布雷病" in answer
    assert "没有完成联网检索" in answer
    assert "不能可靠地列出" in answer
    assert answer.endswith(SAFETY_NOTICE)


def test_search_failure_is_not_mislabeled_as_no_results():
    answer = no_evidence_reply("法布雷病是什么", result(local="failed", web="failed"))
    assert answer is not None
    assert "检索暂时失败" in answer
    assert "联网检索未能完成" in answer
    assert "没有找到" not in answer


def test_search_empty_is_distinct_from_search_skipped():
    answer = no_evidence_reply("阿尔法胶囊有什么副作用", result(web="empty"))
    assert answer is not None
    assert "联网检索也没有找到" in answer


def test_named_disease_card_request_does_not_escape_gate():
    answer = no_evidence_reply("法布雷病请生成科普卡片", result())
    assert answer is not None
    assert "法布雷病" in answer


def test_existing_evidence_and_user_document_keep_normal_answer_path():
    assert no_evidence_reply("法布雷病是什么", result(items=[{"title": "资料"}])) is None
    assert no_evidence_reply("法布雷病是什么", result(), has_user_document=True) is None


def test_symptom_question_without_named_topic_is_not_blocked():
    assert no_evidence_reply("我头痛两天了怎么办", result()) is None
    nonmedical = {**result(), "retrieval_gate_reason": "non_medical_content"}
    assert no_evidence_reply("你好", nonmedical) is None
