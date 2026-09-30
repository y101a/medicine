"""Deterministic intent gate for medical educational DOCX/PPTX requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

DocumentFormat = Literal["docx", "pptx"]

_ACTION = re.compile(r"(?:帮我|请|想要?|能不能|可以)?(?:生成|制作|创建|做|整理成)")
_DOCX = re.compile(r"(?:Word|DOCX|文档)", re.IGNORECASE)
_PPTX = re.compile(r"(?:PPTX?|演示文稿|幻灯片)", re.IGNORECASE)
_NEGATED = re.compile(
    r"(?:不要|不用|无需|别)(?:再|给我|帮我|替我|直接|自动)*"
    r".{0,6}(?:生成|制作|创建|做|整理成)"
)
_ABILITY_ONLY = re.compile(
    r"(?:能|会|可以|支持).{0,8}(?:生成|制作).{0,8}"
    r"(?:PPTX?|Word|DOCX|文档|演示文稿|幻灯片)(?:吗|么|？|\?)?$",
    re.IGNORECASE,
)
_MEDICAL_TOPIC = re.compile(
    r"(?:人体|解剖|器官|组织|细胞|骨骼|肌肉|关节|血管|心脏|肺|肝|肾|胃|肠|脑|神经|"
    r"呼吸|消化|循环|内分泌|免疫|泌尿|生殖|皮肤|眼|耳|鼻|口腔|疾病|病理|炎症|感染|"
    r"过敏|肿瘤|癌|预防|康复|健康|就医|急救|症状|疼痛|头痛|发热|咳嗽|血压|血糖|"
    r"[一-鿿]{1,12}(?:炎|病|症|癌|瘤))"
)
_FORBIDDEN = re.compile(
    r"(?:诊断证明|疾病证明|病历证明|医院公章|医生签名|处方|药方|用药剂量|"
    r"手术同意书|医学鉴定|假条|伪造|冒充)"
)
_TEMPLATE_REQUEST = re.compile(r"(?:模板|套版)")
_TEMPLATE_NEGATED = re.compile(r"(?:不要|不用|无需|不需要|不使用|别用).{0,6}(?:模板|套版)")
_STRIP = re.compile(
    r"(?:帮我|请)(?=(?:使用|采用|套用|按|用))|"
    r"(?:帮我|请|想要?|能不能|可以)?(?:生成|制作|创建|做|整理成)|"
    r"(?:一份|一个|一套)|(?:PPTX?|Word|DOCX|文档|演示文稿|幻灯片)|"
    r"(?:关于|主题是|主题为)|"
    r"(?:不要|不用|无需|不需要|不使用|别用).{0,6}(?:模板|套版)|"
    r"(?:使用|采用|套用|按|用)?(?:内置|默认)?(?:模板|套版)",
    re.IGNORECASE,
)

MAX_REQUEST_CHARS = 500


@dataclass(frozen=True, slots=True)
class DocumentGenerationRequest:
    formats: tuple[DocumentFormat, ...]
    topic: str
    template_requested: bool = False


def medical_document_generation_request(content: str) -> DocumentGenerationRequest | None:
    normalized = " ".join(content.split())
    if not normalized or len(normalized) > MAX_REQUEST_CHARS:
        return None
    if _NEGATED.search(normalized) or _ABILITY_ONLY.fullmatch(normalized):
        return None
    if not _ACTION.search(normalized) or not _MEDICAL_TOPIC.search(normalized):
        return None
    formats: list[DocumentFormat] = []
    if _DOCX.search(normalized):
        formats.append("docx")
    if _PPTX.search(normalized):
        formats.append("pptx")
    if not formats:
        return None
    topic = re.sub(r"\s+", " ", _STRIP.sub(" ", normalized)).strip(" ，,。.!！?？：:")
    if len(topic) < 2:
        return None
    template_requested = bool(
        "pptx" in formats
        and _TEMPLATE_REQUEST.search(normalized)
        and not _TEMPLATE_NEGATED.search(normalized)
    )
    return DocumentGenerationRequest(
        formats=tuple(formats), topic=topic[:300], template_requested=template_requested
    )


def request_contains_forbidden_document(content: str) -> bool:
    return bool(_FORBIDDEN.search(content))
