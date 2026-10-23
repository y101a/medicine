import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.schemas.consultations import TriageResult

TRIAGE_RULESET_VERSION = "2026-09-10.2"


@dataclass(frozen=True, slots=True)
class RedFlagRule:
    id: str
    reason: str
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TriageAssessment:
    route: Literal["emergency", "continue"]
    rule_version: str
    matched_rule_ids: tuple[str, ...]
    result: TriageResult | None

    def as_langgraph_state(self) -> dict[str, object]:
        return {
            "triage_route": self.route,
            "triage_rule_version": self.rule_version,
            "triage_rule_ids": list(self.matched_rule_ids),
            "triage_result": (self.result.model_dump(mode="json") if self.result else None),
        }


RED_FLAG_RULES = (
    RedFlagRule(
        "cardiorespiratory_arrest",
        "可能发生呼吸或心搏骤停",
        ("停止呼吸", "呼吸停止", "心跳停止", "心脏骤停", "没有正常呼吸", "无正常呼吸"),
    ),
    RedFlagRule(
        "altered_consciousness",
        "昏迷或意识异常",
        ("昏迷", "叫不醒", "意识丧失", "意识不清", "神志不清", "突然晕厥"),
    ),
    RedFlagRule(
        "severe_breathing_problem",
        "明显呼吸困难或窒息",
        ("呼吸困难", "喘不上气", "无法呼吸", "不能呼吸", "窒息", "停止呼吸"),
    ),
    RedFlagRule(
        "acute_chest_pain",
        "胸痛或胸部明显压迫感",
        ("胸痛", "胸口疼", "胸口痛", "胸部压迫感", "胸部压榨感", "濒死感"),
    ),
    RedFlagRule(
        "seizure",
        "抽搐或严重痉挛",
        ("抽搐", "全身痉挛", "癫痫大发作"),
    ),
    RedFlagRule(
        "severe_bleeding",
        "严重或无法止住的出血",
        ("大出血", "血流不止", "止不住血", "喷射状出血", "大量呕血", "大量咳血"),
    ),
    RedFlagRule(
        "stroke_warning",
        "可能的急性脑卒中表现",
        (
            "口角歪斜",
            "嘴角歪斜",
            "一侧肢体无力",
            "单侧肢体无力",
            "一边手脚无力",
            "言语不清",
            "说话含糊不清",
            "突然走不稳",
            "突然失去平衡",
            "突然看不清",
            "突然视物模糊",
            "一过性黑蒙",
            "突然单侧麻木",
            "突然一侧麻木",
        ),
    ),
    RedFlagRule(
        "sudden_severe_headache",
        "突发且异常剧烈的头痛",
        ("突发剧烈头痛", "突然剧烈头痛", "爆炸样头痛", "雷击样头痛", "有生以来最严重的头痛"),
    ),
    RedFlagRule(
        "severe_trauma",
        "可能造成严重伤害的创伤",
        (
            "车祸重伤",
            "严重车祸伤",
            "高处坠落",
            "从高处摔下",
            "头部重伤",
            "严重头部外伤",
            "颈部重伤",
            "被重物压住",
            "大面积烧伤",
            "严重烧伤",
            "踩踏受伤",
        ),
    ),
    RedFlagRule(
        "pregnancy_emergency",
        "孕产期大量出血、抽搐或剧烈腹痛",
        ("孕期大出血", "怀孕大量出血", "产后大出血", "孕妇抽搐", "怀孕剧烈腹痛并出血"),
    ),
    RedFlagRule(
        "imminent_self_harm",
        "可能存在立即自伤或自杀危险",
        (
            "准备自杀",
            "正在自杀",
            "想马上自杀",
            "准备跳楼",
            "正在跳楼",
            "正在割腕",
            "已经割腕",
            "控制不住想伤害自己",
            "已经服药自杀",
        ),
    ),
    RedFlagRule(
        "life_threatening_exposure",
        "可能危及生命的意外或中毒",
        ("溺水", "触电", "煤气中毒", "一氧化碳中毒", "误食农药", "服药过量"),
    ),
)

NEGATION_BEFORE = re.compile(r"(?:没有|没|无|未出现|不伴有?|否认|并无|不是)[^，。！？；]{0,6}$")
HISTORY_BEFORE = re.compile(r"(?:既往|曾经|以前|过去|多年前)[^，。！？；]{0,6}$")
RESOLVED_AFTER = re.compile(r"^(?:已经?|现已)?(?:缓解|好了|消失|恢复)")
SPLIT_SENTENCE = re.compile(r"[，,。.!！?？；;\n]+")
CHEST_PAIN_PATTERN = re.compile(r"胸(?:口|部)?[^，。！？；]{0,6}(?:痛|疼|压迫|压榨|憋闷)")
STROKE_SPEECH_PATTERN = re.compile(r"(?:说话|讲话|言语)(?:突然|开始|变得)?(?:含糊不清|含混不清)")
STROKE_WEAKNESS_PATTERN = re.compile(
    r"(?:半边身子|半边身体|一侧身体|一边身子)(?:突然)?(?:使不上劲|没劲|无力)"
)
PREGNANCY_EMERGENCY_PATTERN = re.compile(
    r"(?:孕妇|怀孕|孕期|产后)[^，。！？；]{0,8}(?:大量出血|大出血|抽搐|剧烈腹痛)"
)
EDUCATIONAL_CONTEXT = re.compile(
    r"(?:什么是|是什么意思|请解释|科普(?:一下)?|有哪些(?:症状|原因)|"
    r"常见原因|如何识别|怎么识别|如果出现|假如出现)"
)
CURRENT_CONTEXT = re.compile(
    r"(?:(?:我|本人|家人|孩子|老人|他|她|患者)"
    r"(?:现在|目前|刚才|刚刚|突然|正在|有|出现|感觉|发生)|"
    r"^(?:现在|目前|刚才|刚刚|突然|正在|已经出现))"
)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().replace("　", " ")


def _educational_only(sentence: str) -> bool:
    return bool(EDUCATIONAL_CONTEXT.search(sentence)) and not CURRENT_CONTEXT.search(sentence)


def _active_term(sentence: str, term: str) -> bool:
    if _educational_only(sentence):
        return False
    start = 0
    while (index := sentence.find(term, start)) >= 0:
        before = sentence[max(0, index - 12) : index]
        after = sentence[index + len(term) : index + len(term) + 8]
        if not NEGATION_BEFORE.search(before) and not HISTORY_BEFORE.search(before):
            if not RESOLVED_AFTER.search(after):
                return True
        start = index + len(term)
    return False


def _active_pattern(sentence: str, pattern: re.Pattern[str]) -> bool:
    if _educational_only(sentence):
        return False
    for match in pattern.finditer(sentence):
        before = sentence[max(0, match.start() - 12) : match.start()]
        after = sentence[match.end() : match.end() + 8]
        if not NEGATION_BEFORE.search(before) and not HISTORY_BEFORE.search(before):
            if not RESOLVED_AFTER.search(after):
                return True
    return False


def _allergy_emergency(sentences: list[str]) -> bool:
    allergy_terms = ("过敏性休克", "喉头水肿", "严重过敏", "全身风团", "嘴唇肿", "舌头肿")
    airway_terms = ("呼吸困难", "喘不上气", "吞咽困难", "无法说话", "喉咙发紧")
    if any(
        _active_term(sentence, term)
        for sentence in sentences
        for term in ("过敏性休克", "喉头水肿")
    ):
        return True
    has_allergy = any(
        _active_term(sentence, term) for sentence in sentences for term in allergy_terms
    )
    has_airway_problem = any(
        _active_term(sentence, term) for sentence in sentences for term in airway_terms
    )
    return has_allergy and has_airway_problem


def evaluate_triage(content: str, assessed_at: datetime | None = None) -> TriageAssessment:
    sentences = [part.strip() for part in SPLIT_SENTENCE.split(_normalize(content)) if part.strip()]
    matched_ids: list[str] = []
    reasons: list[str] = []
    for rule in RED_FLAG_RULES:
        matched = any(_active_term(sentence, term) for sentence in sentences for term in rule.terms)
        if rule.id == "acute_chest_pain" and not matched:
            matched = any(_active_pattern(sentence, CHEST_PAIN_PATTERN) for sentence in sentences)
        if rule.id == "stroke_warning" and not matched:
            matched = any(
                _active_pattern(sentence, pattern)
                for sentence in sentences
                for pattern in (STROKE_SPEECH_PATTERN, STROKE_WEAKNESS_PATTERN)
            )
        if rule.id == "pregnancy_emergency" and not matched:
            matched = any(
                _active_pattern(sentence, PREGNANCY_EMERGENCY_PATTERN) for sentence in sentences
            )
        if matched:
            matched_ids.append(rule.id)
            reasons.append(rule.reason)
    if _allergy_emergency(sentences):
        matched_ids.append("severe_allergic_reaction")
        reasons.append("伴呼吸道症状的严重过敏反应")
    if not matched_ids:
        return TriageAssessment(
            route="continue",
            rule_version=TRIAGE_RULESET_VERSION,
            matched_rule_ids=(),
            result=None,
        )

    unique_ids = tuple(dict.fromkeys(matched_ids))
    actions = [
        "请立即拨打中国大陆急救电话 120，并向调度员说明症状和所在位置。",
        "请勿独自驾车前往医院；保持电话畅通并听从 120 调度员指导。",
        "如患者失去意识或停止正常呼吸，请立即告知调度员并按其指导施救。",
    ]
    if "imminent_self_harm" in unique_ids:
        actions = [
            "如已采取自伤行动或无法保证当前安全，请立即拨打 120 或 110。",
            "请不要独处，立即联系身边可信任的人陪同，并远离可能造成伤害的物品。",
            "在保证当前安全的前提下，也可拨打全国统一心理援助热线 12356 寻求支持。",
        ]

    result = TriageResult(
        level="emergency",
        rule_version=TRIAGE_RULESET_VERSION,
        assessment_method="deterministic_rules",
        title="可能存在紧急情况",
        summary="系统从您的描述中检测到需要优先处理的危险信号。",
        reasons=list(dict.fromkeys(reasons)),
        actions=actions,
        rule_ids=list(unique_ids),
        assessed_at=assessed_at or datetime.now(UTC),
    )
    return TriageAssessment(
        route="emergency",
        rule_version=TRIAGE_RULESET_VERSION,
        matched_rule_ids=unique_ids,
        result=result,
    )


def assess_red_flags(content: str, assessed_at: datetime | None = None) -> TriageResult | None:
    return evaluate_triage(content, assessed_at).result


def serialize_triage(result: TriageResult) -> str:
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def deserialize_triage(value: str | None) -> TriageResult | None:
    return TriageResult.model_validate_json(value) if value else None
