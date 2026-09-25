"""Deterministic intent gate for explicit medical illustration requests."""

from __future__ import annotations

import re

_ACTION = re.compile(
    r"(?:帮我|请|想要?|能不能|可以)?(?:生成|绘制|画|制作|创建|做)(?:一张|一个|幅)?"
)
_IMAGE = re.compile(r"(?:图片|图像|插图|示意图|结构图|科普图|配图)")
_NEGATED = re.compile(
    r"(?:不要|不用|无需|别)(?:再|给我|帮我|替我|直接|自动)*"
    r"(?:生成|绘制|画|制作|创建|做)"
)
_MEDICAL_TOPIC = re.compile(
    r"(?:人体|解剖|器官|组织|细胞|骨骼|肌肉|关节|血管|心脏|肺|肝|肾|胃|肠|脑|神经|"
    r"呼吸|消化|循环|内分泌|免疫|泌尿|生殖|皮肤|眼|耳|鼻|口腔|疾病|病理|炎症|感染|"
    r"过敏|肿瘤|癌|预防|康复|健康|就医|急救|症状|疼痛|头痛|发热|咳嗽|"
    r"[\u4e00-\u9fff]{1,12}(?:炎|病|症|癌|瘤))"
)

MAX_INTENT_PROMPT_CHARS = 500


def medical_image_generation_prompt(content: str) -> str | None:
    """Return the original normalized prompt only for an explicit allowed request."""
    normalized = " ".join(content.split())
    if not normalized or len(normalized) > MAX_INTENT_PROMPT_CHARS:
        return None
    if _NEGATED.search(normalized):
        return None
    if not _ACTION.search(normalized) or not _IMAGE.search(normalized):
        return None
    if not _MEDICAL_TOPIC.search(normalized):
        return None
    return normalized
