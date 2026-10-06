"""稿件与来源原文的确定性比对：引文一致性（A 类）不依赖模型的实现。

动机：第三方医疗 AI 在「复述有害内容」上会随机拒答——同一段稿件实测两次，
一次给出完整筛查表、一次直接拒答，因此它不能当上线前的验收关卡。
这里用纯本地、可复现的句子级比对给出 A 类结论：

- A1 稿件句子在来源原文里找不到对应句（字符 3-gram 覆盖率低于阈值，逐句比较）；
- A2 情态升级：来源用「可考虑/建议/可能」这类留有余地的措辞，稿件出现「一定/必须/只要」
  （整篇比较：高危句往往整句都没有来源，绑在同一句上会漏）；
- A3 限定条件丢失：来源写了人群/情形限定（如「没有运动禁忌的成年人」），稿件里消失（整篇比较）。
- B 类（剂量、药名、疗程、确诊口气、个人运动处方、疗效承诺…）沿用 prototype_precheck
  的规则与上下文抑制，两处口径保持一致。

输出永远只是「疑似，待人工确认」：不判定医学正确性，不代替执业医师签字。

命令行（不需要数据库、不联网）：
    python -m app.rag.draft_source_check --draft 稿件.txt --source 来源.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.rag.prototype_precheck import has_escalation, scan_text_with_suppression

__all__ = [
    "SOFT_MODALS",
    "HARD_MODALS",
    "QUALIFIERS",
    "COVERAGE_THRESHOLD",
    "DraftCheckResult",
    "split_sentences",
    "coverage",
    "best_match",
    "compare_draft",
    "main",
]

_SENTENCE_SPLIT = re.compile(r"[。！？；\n]+")

#: 来源里的「留有余地」措辞；稿件出现 HARD_MODALS 就是情态升级。
SOFT_MODALS = (
    "可能",
    "可考虑",
    "可适量",
    "可根据",
    "考虑",
    "适量",
    "建议",
    "酌情",
    "一般",
    "多数",
    "通常",
    "有助于",
)

#: 绝对化措辞。
HARD_MODALS = ("一定", "必须", "只要", "必然", "肯定", "绝对", "都能", "就能", "保证")

#: 限定条件：来源写了而稿件没写，就是丢了限定。
QUALIFIERS = (
    "没有运动禁忌",
    "成年人",
    "儿童",
    "婴幼儿",
    "老年人",
    "老年",
    "孕妇",
    "哺乳期",
    "慢性病",
    "糖尿病",
    "高血压",
    "过敏",
    "空腹",
    "餐后",
    "急性期",
    "确诊",
)

#: 元话语/免责句不需要来源支撑（「本文不提供…」「请咨询医生」）。
_META_CUES = ("本文", "本稿", "请咨询医生", "仅供参考", "侵删", "科普", "不提供", "不构成")

MIN_SENTENCE_LENGTH = 8
COVERAGE_THRESHOLD = 0.42


@dataclass
class DraftCheckResult:
    draft_sentence_count: int = 0
    source_sentence_count: int = 0
    unsourced: list[dict[str, object]] = field(default_factory=list)
    modal_upgrades: list[dict[str, object]] = field(default_factory=list)
    dropped_qualifiers: list[dict[str, object]] = field(default_factory=list)
    boundary_findings: list[dict[str, object]] = field(default_factory=list)
    suppressed_counts: dict[str, int] = field(default_factory=dict)
    missing_escalation: bool = False
    note: str = (
        "机器比对只做定位，结论一律「疑似，待人工确认」；"
        "不判定医学正确性，不出「通过」，不代替签字。"
    )


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def _ngrams(text: str, size: int = 3) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def coverage(sentence: str, source_sentence: str) -> float:
    """稿件句有多少比例的字面 3-gram 出现在来源句里。"""
    draft_grams = _ngrams(sentence)
    source_grams = _ngrams(source_sentence)
    if not draft_grams or not source_grams:
        return 0.0
    return len(draft_grams & source_grams) / len(draft_grams)


def best_match(sentence: str, source_sentences: list[str]) -> tuple[float, str]:
    best_score = 0.0
    best_sentence = ""
    for candidate in source_sentences:
        score = coverage(sentence, candidate)
        if score > best_score:
            best_score, best_sentence = score, candidate
    return best_score, best_sentence


def _is_meta(sentence: str) -> bool:
    return any(cue in sentence for cue in _META_CUES)


def compare_draft(draft_text: str, source_text: str) -> DraftCheckResult:
    """把稿件与来源原文比对。纯函数、无网络、无数据库、结果可复现。"""
    draft_sentences = split_sentences(draft_text)
    source_sentences = split_sentences(source_text)
    result = DraftCheckResult(
        draft_sentence_count=len(draft_sentences),
        source_sentence_count=len(source_sentences),
    )
    result.missing_escalation = not has_escalation(draft_text)

    # A1：逐句找来源，找不到的单列。
    for sentence in draft_sentences:
        if len(sentence) < MIN_SENTENCE_LENGTH or _is_meta(sentence):
            continue
        score, matched = best_match(sentence, source_sentences)
        if score < COVERAGE_THRESHOLD:
            result.unsourced.append(
                {
                    "sentence": sentence,
                    "best_coverage": round(score, 4),
                    "nearest_source": matched,
                    "why": "来源原文里找不到对应句（字面覆盖率低于阈值）",
                }
            )

    # A2/A3：整篇比较。高危句常常整句都找不到来源（覆盖率低），
    # 如果绑在「同一句」上，情态升级与丢限定都会被跳过，所以按整篇判断。
    upgrade = [word for word in HARD_MODALS if word in draft_text]
    soft = [word for word in SOFT_MODALS if word in source_text]
    if upgrade and soft:
        result.modal_upgrades.append(
            {
                "hard_words_in_draft": upgrade,
                "source_soft_words": soft,
                "why": "来源用的是留有余地的措辞，稿件出现绝对化措辞",
            }
        )
    dropped = [word for word in QUALIFIERS if word in source_text and word not in draft_text]
    if dropped:
        result.dropped_qualifiers.append(
            {"dropped": dropped, "why": "来源里的限定条件在稿件中消失"}
        )

    # B 类：沿用同一套规则与上下文抑制。
    for finding in scan_text_with_suppression(draft_text):
        if finding.suppressed:
            key = f"{finding.rule}:{finding.suppression_reason}"
            result.suppressed_counts[key] = result.suppressed_counts.get(key, 0) + 1
            continue
        result.boundary_findings.append(
            {"rule": finding.rule, "label": finding.label, "snippet": finding.snippet}
        )
    result.suppressed_counts = dict(sorted(result.suppressed_counts.items()))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="稿件与来源原文的确定性比对（本地、可复现）")
    parser.add_argument("--draft", type=Path, default=None, help="稿件文件")
    parser.add_argument("--source", type=Path, default=None, help="来源原文文件")
    parser.add_argument("--draft-text", default=None, help="直接给稿件文本")
    parser.add_argument("--source-text", default=None, help="直接给来源文本")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    draft_text = args.draft_text or (args.draft.read_text(encoding="utf-8") if args.draft else "")
    source_text = args.source_text or (
        args.source.read_text(encoding="utf-8") if args.source else ""
    )
    if not draft_text:
        print(json.dumps({"ok": False, "error": "必须给出稿件：--draft 或 --draft-text"}))
        return 1
    result = compare_draft(draft_text, source_text)
    print(json.dumps({"ok": True, **asdict(result)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())