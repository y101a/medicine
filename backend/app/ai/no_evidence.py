"""Deterministic reply for named medical topics with no usable evidence."""

import re
from collections.abc import Mapping

from app.rag.web_search import UNKNOWN_TERM, allowed_search_topic, safe_search_topic

SAFETY_NOTICE = "以上仅供健康科普参考，不作确诊，不能替代医生面诊。"
TOPIC_AT_START = re.compile(
    rf"^(?:请问|我想了解)?\s*({UNKNOWN_TERM.pattern})(?=的|请|科普|卡片|常见|$)"
)
HIGH_RISK_REQUEST = re.compile(
    r"怎么治|治疗|确诊|诊断|吃什么药|用什么药|能吃吗|能不能吃|"
    r"剂量|用量|吃多少|停药|换药|用药|处方|手术"
)


def unverified_web_risk_reply(
    user_text: str,
    retrieval: Mapping[str, object],
    *,
    has_user_document: bool = False,
) -> str | None:
    """Block high-risk advice when every retrieved citation is an unverified site."""
    items = retrieval.get("retrieval_items")
    if has_user_document or not isinstance(items, list) or not items:
        return None
    if not HIGH_RISK_REQUEST.search(user_text):
        return None
    if not all(
        isinstance(item, Mapping)
        and item.get("source_key") == "web_search_prototype"
        and str(item.get("organization", "")).startswith("未核实网站（")
        for item in items
    ):
        return None
    return (
        "本轮只找到未经医学审核的网站搜索摘要，不能据此给出个人诊断、治疗方案、"
        "药物剂量或停换药建议。你可以先把网页信息当作进一步核实的线索，"
        "具体决策请向医生或药师咨询。\n\n" + SAFETY_NOTICE
    )


def named_topic(user_text: str) -> str | None:
    topic = safe_search_topic(user_text)
    if topic is not None:
        return topic
    match = TOPIC_AT_START.search(user_text.strip())
    if match and allowed_search_topic(match.group(1)):
        return match.group(1)
    return None


def no_evidence_reply(
    user_text: str,
    retrieval: Mapping[str, object],
    *,
    has_user_document: bool = False,
) -> str | None:
    """Do not ask a model to invent disease/drug details when evidence is absent.

    This is intentionally narrow: ordinary symptom triage, emergency routing,
    and questions backed by public or user-provided documents use their existing paths.
    """
    if retrieval.get("retrieval_gate_reason") != "medical_content":
        return None
    if retrieval.get("retrieval_items") or has_user_document:
        return None
    topic = named_topic(user_text)
    if topic is None:
        return None

    local_status = retrieval.get("retrieval_status")
    web_status = retrieval.get("web_search_status")
    if web_status == "failed":
        search_note = "联网检索未能完成，不能把搜索失败当成已经核实。"
    elif web_status == "empty":
        search_note = "本轮受限联网检索也没有找到足够相关的资料。"
    elif web_status == "skipped":
        search_note = "本轮没有完成联网检索。"
    else:
        search_note = "本轮没有可用于核实的检索资料。"
    if local_status == "failed":
        local_note = "本地资料检索暂时失败。"
    else:
        local_note = "本地知识库没有找到足够相关的资料。"

    return (
        f"关于「{topic}」，{local_note}{search_note}"
        "因此我现在不能可靠地列出它的具体表现、风险或治疗方式，也不会仅凭模型记忆补写。"
        "你可以核对病名或药名后再试；若这是你本人正在面对的健康问题，"
        "请向医生或药师核实。\n\n"
        + SAFETY_NOTICE
    )
