"""抽取资格判定：只看用户消息本身，与检索门控、助手标记无关。

覆盖用户 2026-09-30 上报的缺陷：真实自述「我最近总口渴」「最近感觉身体状态不错：脸上
红红的」被 RAG 门控判成 ``non_medical_content``，于是采集开着也不落库。这些用例把
「该抽」与「不该抽」的边界钉住，并**结构化地**锁住解耦（不得再 import 检索门控）。
"""

import ast
import importlib
from pathlib import Path

import pytest

from app.ai.graph.retrieval_gate import evaluate_retrieval_gate
from app.ai.health_eligibility import evaluate_health_extraction_eligibility

ELIGIBLE_SELF_REPORTS = [
    "我最近总口渴",
    "最近感觉身体状态不错：脸上红红的",
    "我这两天嗓子疼得厉害",
    "我一直在吃降压药",
    "我对青霉素过敏",
    "我血压有点高，量了145",
    "我最近熬夜很多，作息乱",
    "我失眠好几个月了",
    "我每天抽一包烟",
    "我昨天去医院复查了",
    "我最近压力大，心情不好",
    "头晕",
    "拉肚子两天了",
    "我妈有糖尿病，我最近也总口渴",
    "我孩子发烧了，我也有点咳嗽",
]

INELIGIBLE_WITH_REASON = [
    ("", "empty"),
    ("你好", "social-only"),
    ("你好呀！", "social-only"),
    ("谢谢", "social-only"),
    ("你是谁", "identity-question"),
    ("你是什么模型", "identity-question"),
    ("介绍一下你自己", "identity-question"),
    ("讲个笑话", "off-topic-request"),
    ("你会自动定期更新健康记录吗", "product-capability"),
    ("你会记录我的健康信息吗", "product-capability"),
    ("怎么关闭采集", "product-capability"),
    ("我的健康记录存在哪里", "product-capability"),
    ("我记录里有没有糖尿病", "record-query"),
    ("我之前说过什么", "record-query"),
    ("糖尿病是什么", "general-knowledge-question"),
    ("高血压能治好吗", "general-knowledge-question"),
    ("我朋友最近总口渴", "third-party"),
    ("我妈有高血压", "third-party"),
    ("今天天气不错", "off-topic-request"),
    ("帮我写一段代码", "off-topic-request"),
    ("我今年45岁", "no-health-content"),
]


@pytest.mark.parametrize("text", ELIGIBLE_SELF_REPORTS)
def test_self_reports_are_eligible(text: str) -> None:
    decision = evaluate_health_extraction_eligibility(text)
    assert decision.eligible is True
    assert decision.reason == "self-disclosure"


@pytest.mark.parametrize(("text", "reason"), INELIGIBLE_WITH_REASON)
def test_non_self_reports_are_skipped_with_a_reason(text: str, reason: str) -> None:
    decision = evaluate_health_extraction_eligibility(text)
    assert decision.eligible is False
    assert decision.reason == reason


def test_the_two_reported_self_reports_are_where_the_old_gate_said_no_medical_content() -> None:
    """行为证据：同一条消息，旧门控说“非医疗内容”，新资格判定说“该抽”。"""

    for text in ("我最近总口渴", "最近感觉身体状态不错：脸上红红的"):
        assert evaluate_retrieval_gate(text).should_retrieve is False
        assert evaluate_health_extraction_eligibility(text).eligible is True


def test_product_capability_question_is_never_stored_as_a_health_fact() -> None:
    for text in (
        "你会自动定期更新健康记录吗",
        "你会不会自动保存我说的症状",
        "健康记录会自动更新吗",
        "怎么删除我的健康记录",
    ):
        assert evaluate_health_extraction_eligibility(text).eligible is False


def test_third_party_only_reports_are_rejected_but_mixed_messages_are_kept() -> None:
    assert evaluate_health_extraction_eligibility("我妈妈有高血压").reason == "third-party"
    assert evaluate_health_extraction_eligibility("我同事最近总咳嗽").reason == "third-party"
    # 同一句里既有他人也有用户本人自述时不能整条丢掉，否则会漏掉用户自己的事实。
    mixed = evaluate_health_extraction_eligibility("我妈有糖尿病，我最近也总口渴")
    assert mixed.eligible is True


def test_eligibility_module_imports_no_retrieval_gate_and_no_assistant_flag() -> None:
    """结构性锁：资格判定不得再依赖 RAG 门控或 ``Message.is_medical_content``。"""

    module = importlib.import_module("app.ai.health_eligibility")
    source = Path(module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported == {"re", "unicodedata", "dataclasses", "typing"}
