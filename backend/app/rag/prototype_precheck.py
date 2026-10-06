"""原型语料的人工审核前机器预审：只出「疑似越界句」清单，不改任何审核状态。

定位（配套 backend/docs/KNOWLEDGE_FOUR_LAYER_GAP_PLAN.md 的人工验收）：
- 机器只能筛掉**明显**越界表述：具体剂量、疗程/停药指令、具体药名、
  确诊口气、个人运动处方、疗效承诺，以及缺就医分流。
- 机器**不判定**医学正确性，也**不出「通过」结论**；每条结论一律是「疑似，待人工确认」。
- 因此本模块只读数据库，不写状态、不改成 approved、不写审计。

设计要点（2026-10-06 修复）：第一版只做关键词匹配，真实语料上 16 条命中**全是误报**
（把「不要擅自停药」当成停药指令、把「食盐不超过 5 克」当成剂量、
把「不一定是疼」当成确诊口气）。
因此本版加入**上下文抑制**：安全提醒句、膳食与生理限量、非用药的「减量」、
免责声明句、描述「正在服用」某药的句子一律不计入违规。
被抑制的条目**不静默丢弃**：单独计数并给出原因，供人工复核。

已知代价：句内出现否定线索时整句抑制，会漏掉「不要自行停药，但可以改成每天 2 片」
这类混合句；因此抑制条目仍然逐条计数，不能只看未被抑制的数字。

也正因为机器完全本地、只做匹配与定位，它不需要任何模型政策豁免：
模型拒绝「复述药名剂量」不代表这条链路不可用，本模块不生成医学结论，只定位。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource

__all__ = [
    "PRECHECK_RULES",
    "ESCALATION_PATTERN",
    "NEGATION_CUES",
    "DIETARY_LIMIT_CONTEXT",
    "DISCLAIMER_CUES",
    "NON_MEDICATION_CONTEXT",
    "PrecheckFinding",
    "PrecheckResult",
    "scan_text",
    "scan_text_with_suppression",
    "has_escalation",
    "precheck_prototype_documents",
]

# 每条规则只做「可疑定位」，不代替医学判断；命中的每句都要由人解释该删还是该改。
PRECHECK_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "dosage",
        "出现具体剂量（本产品不给出个体用药剂量）",
        re.compile(
            r"\d+(?:\.\d+)?\s*(?:mg|毫克|g|克|ml|毫升|片|粒|IU|国际单位|微克|ug)"
        ),
    ),
    (
        "regimen",
        "出现疗程/停药/加减量等用药指令",
        re.compile(
            r"疗程|吃几天|连吃|加量|减量|自行停药|停药后|再吃|加倍|连续\s*\d+\s*(?:天|周)"
        ),
    ),
    (
        "drug_name",
        "出现具体药品名或服药指令（不得代开处方或推荐具体药）",
        re.compile(
            r"阿莫西林|头孢|阿奇霉素|左氧氟沙星|布洛芬|对乙酰氨基酚|奥司他韦|甲硝唑|青霉素|红霉素"
            r"|服用[^。；\n]{0,12}药"
        ),
    ),
    (
        "diagnosis_tone",
        "确诊口气（不得据症状下诊断）",
        re.compile(r"你就是|说明你得了|可以确诊|一定是|肯定是|毫无疑问是|基本可以断定"),
    ),
    (
        "personal_prescription",
        "个人运动处方/强度目标（不得对具体人给运动处方）",
        re.compile(
            r"(?:你|您|患者)[^。；\n]{0,16}(?:心率|配速|强度|每组|每周\s*\d+\s*次|每天\s*\d+\s*分钟)"
        ),
    ),
    (
        "efficacy_claim",
        "疗效承诺（不得承诺治愈或一定有效）",
        re.compile(r"能治好|可以治好|根治|保证有效|一定有效|药到病除|彻底治愈"),
    ),
)

# 科普内容必须保留及时就医分流；缺失本身就要人工补写。
ESCALATION_PATTERN = re.compile(r"及时就医|尽快就医|就医|就诊|急诊|120|急救|去医院")

#: 否定/安全提醒线索：命中这些时，句子多半是在**劝阻**该行为，不算越界。
NEGATION_CUES = ("不", "别", "勿", "避免", "禁止", "切勿", "不要", "不应", "不得", "非", "无")

#: 膳食与生理限量：克/毫升出现在这些语境里是营养建议，不是药品剂量。
DIETARY_LIMIT_CONTEXT = (
    "食盐",
    "盐",
    "烹调油",
    "食用油",
    "添加糖",
    "反式脂肪酸",
    "饮水",
    "补水",
    "酒精",
    "能量",
    "蛋白质",
    "脂肪",
    "蔬果",
    "蔬菜",
    "水果",
)

#: 免责声明句：说「本文不给出…疗程/配方」是边界声明，不是指令。
DISCLAIMER_CUES = (
    "本文不",
    "本文件不",
    "不提供",
    "不给出",
    "不作",
    "不构成",
    "侵删",
    "科普",
    "学术交流",
)

#: 非用药语境：出现在这些词附近时，「减量/加量/停止」说的是运动量。
NON_MEDICATION_CONTEXT = ("运动量", "运动强度", "训练", "锻炼", "体力活动")

#: 描述「正在服用某药」是在提醒药物交互风险，不是推荐用药。
TAKING_MEDICATION_CUES = ("正在服用", "长期服用", "服用中的", "已经在服")

#: 需要做上下文抑制的规则（确诊口气与疗效承诺始终计为违规，不做抑制）。
SUPPRESSIBLE_RULES = frozenset({"dosage", "regimen", "drug_name", "personal_prescription"})

_NEGATION_WINDOW = 14
_SENTENCE_BOUNDARY = re.compile(r"[。；！？\n]")


@dataclass(frozen=True)
class PrecheckFinding:
    rule: str
    label: str
    snippet: str
    suppressed: bool = False
    suppression_reason: str | None = None


@dataclass
class PrecheckResult:
    document_count: int = 0
    chunk_count: int = 0
    flagged_document_count: int = 0
    missing_escalation_document_count: int = 0
    finding_counts: dict[str, int] = field(default_factory=dict)
    suppressed_counts: dict[str, int] = field(default_factory=dict)
    documents: list[dict[str, object]] = field(default_factory=list)
    note: str = (
        "机器预审只筛明显越界表述，结论一律为「疑似，待人工确认」；"
        "机器不判定医学正确性，也不得出「通过」。被抑制的疑似条目单独计数，不静默丢弃。"
    )


def _sentence_bounds(text: str, index: int) -> tuple[int, int]:
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        if match.end() <= index:
            start = match.end()
        elif match.start() >= index:
            return start, match.start()
    return start, len(text)


def _suppression_reason(
    text: str, start: int, end: int, match: re.Match[str], rule: str
) -> str | None:
    """返回抑制原因；None 表示这条命中确实要报出来。"""
    if rule == "efficacy_claim":
        # 疗效承诺一律上报：哪怕句子里带否定词，也要人工判断是否在劝阻还是承诺。
        return None
    sentence = text[start:end]
    before = text[max(start, match.start() - _NEGATION_WINDOW) : match.start()]
    if rule == "diagnosis_tone":
        # 只抑制「不一定是…」这类被否定的绝对化；其余确诊口气一律上报。
        immediate = text[max(0, match.start() - 2) : match.start()]
        return "negated_absolute" if "不" in immediate else None
    if any(cue in sentence for cue in DISCLAIMER_CUES):
        return "disclaimer"
    if any(cue in sentence for cue in TAKING_MEDICATION_CUES):
        return "describes_current_medication"
    if any(cue in sentence for cue in NON_MEDICATION_CONTEXT):
        return "non_medication_context"
    # 安全提醒句常把否定写在命中**之后**（「不要因为…就自行停药」），所以按整句判断。
    if any(cue in sentence for cue in NEGATION_CUES) or any(
        cue in before for cue in NEGATION_CUES
    ):
        return "negation"
    if any(word in sentence for word in DIETARY_LIMIT_CONTEXT):
        return "dietary_or_physiological_limit"
    return None


def scan_text_with_suppression(text: str) -> list[PrecheckFinding]:
    """扫一段文本，返回全部命中（含被抑制的），便于复核规则本身是否过严或过松。"""
    findings: list[PrecheckFinding] = []
    if not text:
        return findings
    for rule, label, pattern in PRECHECK_RULES:
        for match in pattern.finditer(text):
            snippet_start = max(0, match.start() - 24)
            snippet_end = min(len(text), match.end() + 24)
            snippet = text[snippet_start:snippet_end].replace("\n", " ").strip()
            start, end = _sentence_bounds(text, match.start())
            reason = _suppression_reason(text, start, end, match, rule)
            findings.append(
                PrecheckFinding(
                    rule=rule,
                    label=label,
                    snippet=snippet,
                    suppressed=reason is not None,
                    suppression_reason=reason,
                )
            )
    return findings


def scan_text(text: str) -> list[PrecheckFinding]:
    """只返回**未被抑制**的疑似越界表述。"""
    return [finding for finding in scan_text_with_suppression(text) if not finding.suppressed]


def has_escalation(text: str) -> bool:
    return bool(ESCALATION_PATTERN.search(text or ""))


async def precheck_prototype_documents(db: AsyncSession) -> PrecheckResult:
    """只读扫描开发环境的 prototype 语料。不写库、不改 review_status。"""
    rows = (
        await db.execute(
            select(KnowledgeDocument, KnowledgeChunk, KnowledgeSource)
            .join(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(
                KnowledgeSource.ingestion_status == "prototype",
                KnowledgeDocument.review_status == "prototype",
            )
            .order_by(KnowledgeDocument.id, KnowledgeChunk.id)
        )
    ).all()

    result = PrecheckResult()
    finding_counts: dict[str, int] = {}
    suppressed_counts: dict[str, int] = {}
    per_document: dict[object, dict[str, object]] = {}
    chunk_seen: set[object] = set()
    document_ids: list[object] = []
    for document, chunk, source in rows:
        if document.id not in per_document:
            document_ids.append(document.id)
        if chunk.id not in chunk_seen:
            chunk_seen.add(chunk.id)
            result.chunk_count += 1
        entry = per_document.setdefault(
            document.id,
            {
                "document_id": str(document.id),
                "slug": getattr(document, "slug", None) or str(document.id),
                "title": document.title,
                "source_key": getattr(source, "source_key", None),
                "findings": [],
                "suppressed": [],
                "escalation": False,
            },
        )
        for finding in scan_text_with_suppression(chunk.content or ""):
            bucket = "suppressed" if finding.suppressed else "findings"
            counters = suppressed_counts if finding.suppressed else finding_counts
            key = (
                f"{finding.rule}:{finding.suppression_reason}"
                if finding.suppressed
                else finding.rule
            )
            counters[key] = counters.get(key, 0) + 1
            target = entry[bucket]
            assert isinstance(target, list)
            target.append(
                {"rule": finding.rule, "label": finding.label, "snippet": finding.snippet}
            )
        if has_escalation(chunk.content or "") or has_escalation(document.title):
            entry["escalation"] = True

    result.document_count = len(document_ids)
    for entry in per_document.values():
        findings = entry["findings"]
        assert isinstance(findings, list)
        if findings:
            result.flagged_document_count += 1
        if not entry["escalation"]:
            result.missing_escalation_document_count += 1
    result.finding_counts = dict(sorted(finding_counts.items()))
    result.suppressed_counts = dict(sorted(suppressed_counts.items()))
    result.documents = list(per_document.values())
    return result