"""原型语料的人工审核前机器预审：只出「疑似越界句」清单，不改任何审核状态。

定位（配套 backend/docs/KNOWLEDGE_FOUR_LAYER_GAP_PLAN.md 的人工验收）：
- 机器只能筛掉**明显**越界表述：具体剂量、疗程/停药指令、具体药名、确诊口气、个人运动处方、疗效承诺，以及缺就医分流。
- 机器**不判定**医学正确性，也**不出「通过」结论**；每条结论一律是「疑似，待人工确认」。
- 因此本模块只读数据库，不写状态、不改成 approved、不写审计。
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
    "PrecheckFinding",
    "PrecheckResult",
    "scan_text",
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
        re.compile(r"疗程|吃几天|连吃|加量|减量|自行停药|停药后|再吃|加倍"),
    ),
    (
        "drug_name",
        "出现具体药品名（不得代开处方或推荐具体药）",
        re.compile(
            r"阿莫西林|头孢|阿奇霉素|左氧氟沙星|布洛芬|对乙酰氨基酚|奥司他韦|甲硝唑|青霉素|红霉素"
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


@dataclass(frozen=True)
class PrecheckFinding:
    rule: str
    label: str
    snippet: str


@dataclass
class PrecheckResult:
    document_count: int = 0
    chunk_count: int = 0
    flagged_document_count: int = 0
    missing_escalation_document_count: int = 0
    finding_counts: dict[str, int] = field(default_factory=dict)
    documents: list[dict[str, object]] = field(default_factory=list)
    note: str = (
        "机器预审只筛明显越界表述，结论一律为「疑似，待人工确认」；"
        "机器不判定医学正确性，也不得出「通过」。"
    )


def scan_text(text: str) -> list[PrecheckFinding]:
    """返回该段文本里命中的疑似越界表述（每条带一段上下文，便于人工定位）。"""
    findings: list[PrecheckFinding] = []
    if not text:
        return findings
    for rule, label, pattern in PRECHECK_RULES:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 24)
            end = min(len(text), match.end() + 24)
            findings.append(
                PrecheckFinding(
                    rule=rule,
                    label=label,
                    snippet=text[start:end].replace("\n", " ").strip(),
                )
            )
    return findings


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
    per_document: dict[object, dict[str, object]] = {}
    chunk_seen: set[object] = set()
    for document, chunk, source in rows:
        result.document_count = len({*per_document, document.id})
        if chunk.id not in chunk_seen:
            chunk_seen.add(chunk.id)
            result.chunk_count += 1
        entry = per_document.setdefault(
            document.id,
            {
                "slug": getattr(document, "slug", None) or str(document.id),
                "title": document.title,
                "source_key": getattr(source, "source_key", None),
                "findings": [],
                "escalation": False,
            },
        )
        findings = scan_text(chunk.content or "")
        for finding in findings:
            finding_counts[finding.rule] = finding_counts.get(finding.rule, 0) + 1
            cast_findings = entry["findings"]
            assert isinstance(cast_findings, list)
            cast_findings.append(
                {"rule": finding.rule, "label": finding.label, "snippet": finding.snippet}
            )
        if has_escalation(chunk.content or "") or has_escalation(document.title):
            entry["escalation"] = True

    for entry in per_document.values():
        findings = entry["findings"]
        assert isinstance(findings, list)
        if findings:
            result.flagged_document_count += 1
        if not entry["escalation"]:
            result.missing_escalation_document_count += 1
    result.finding_counts = dict(sorted(finding_counts.items()))
    result.documents = list(per_document.values())
    return result