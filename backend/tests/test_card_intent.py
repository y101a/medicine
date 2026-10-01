import pytest

from app.ai.card_intent import requests_pathology_card, requests_previous_card
from app.ai.graph.retrieval_gate import evaluate_retrieval_gate


@pytest.mark.parametrize("text", [
    "帮我生成一张头痛科普卡片", "把刚才的回答整理成卡片", "生成卡片",
    "用卡片形式介绍糖尿病", "请制作荨麻疹科普卡",
])
def test_explicit_card_request(text):
    assert requests_pathology_card(text)


@pytest.mark.parametrize("text", [
    "不要生成头痛卡片", "你能不能生成卡片", "如何生成卡片", "生成银行卡",
    "请做生日贺卡", "生成头痛PPT卡片", "头痛怎么办", "生成卡片可以吗",
])
def test_other_intents_remain_plain(text):
    assert not requests_pathology_card(text)


@pytest.mark.parametrize("text", ["血尿", "尿频尿急尿痛", "荨麻疹", "湿疹", "风团"])
def test_new_knowledge_topics_reach_retrieval(text):
    assert evaluate_retrieval_gate(text).should_retrieve


def test_unrelated_topic_must_not_reuse_previous_health_answer():
    assert requests_previous_card("把刚才的回答整理成卡片")
    assert requests_previous_card("生成卡片")
    assert not requests_previous_card("生成天气卡片")
