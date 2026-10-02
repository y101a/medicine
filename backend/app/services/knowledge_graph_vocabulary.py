"""知识图谱的冻结词表（G0）。

`NEO4J_KNOWLEDGE_GRAPH_PLAN.md` 第 5 节的「冻结概念类型、predicate 白名单和证据规则」
在这里落成代码：抽取、审核、发布和将来的 Neo4j 投影都必须以本模块为唯一事实源。
改动等于改图模型——必须同时改文档、迁移与 §7.2 记录，不允许只在一处加 predicate。

为什么每个 predicate 还要钉住两端的类型：`HAS_RED_FLAG` 的宾语必须是红旗、`SUGGESTS_DEPARTMENT`
的宾语必须是科室。少了这层校验，抽取规则或人工导入会把「科室」写成症状的宾语，
到了 Neo4j 才暴露，代价是整轮投影返工。
"""

import unicodedata

from app.models.knowledge_graph import ConceptType, GraphClaimPredicate, GraphClaimStatus


class KnowledgeGraphVocabularyError(ValueError):
    """词表校验失败：未知 predicate、两端类型不匹配、名称规范化后为空。"""


#: 每个 predicate 允许的（主语类型集合，宾语类型集合）。
PREDICATE_TYPE_RULES: dict[
    GraphClaimPredicate, tuple[frozenset[ConceptType], frozenset[ConceptType]]
] = {
    GraphClaimPredicate.MAY_INCLUDE_SYMPTOM: (
        frozenset({ConceptType.TOPIC}),
        frozenset({ConceptType.SYMPTOM}),
    ),
    GraphClaimPredicate.HAS_RED_FLAG: (
        frozenset({ConceptType.TOPIC}),
        frozenset({ConceptType.RED_FLAG}),
    ),
    GraphClaimPredicate.SUGGESTS_DEPARTMENT: (
        frozenset({ConceptType.TOPIC}),
        frozenset({ConceptType.DEPARTMENT}),
    ),
    GraphClaimPredicate.HAS_SELF_CARE_TOPIC: (
        frozenset({ConceptType.TOPIC}),
        frozenset({ConceptType.SELF_CARE}),
    ),
    GraphClaimPredicate.RELATED_TOPIC: (
        frozenset({ConceptType.TOPIC}),
        frozenset({ConceptType.TOPIC}),
    ),
}

#: 给人看的关系说法。刻意用「可能/通常/提醒」这类措辞，不写成因果或诊断结论。
PREDICATE_LABELS: dict[GraphClaimPredicate, str] = {
    GraphClaimPredicate.MAY_INCLUDE_SYMPTOM: "可能出现的表现",
    GraphClaimPredicate.HAS_RED_FLAG: "需要警惕的红旗提醒",
    GraphClaimPredicate.SUGGESTS_DEPARTMENT: "通常咨询的科室",
    GraphClaimPredicate.HAS_SELF_CARE_TOPIC: "自我照护主题",
    GraphClaimPredicate.RELATED_TOPIC: "相关主题",
}

_EDGE_PUNCTUATION = "。，、；：！？…·.,;:!?()（）[]【】{}<>\"'“”‘’《》—－-_/\\|"


def _coerce_predicate(predicate: GraphClaimPredicate | str) -> GraphClaimPredicate:
    if isinstance(predicate, GraphClaimPredicate):
        return predicate
    try:
        return GraphClaimPredicate(predicate)
    except ValueError as exc:
        raise KnowledgeGraphVocabularyError(f"未知关系类型：{predicate}") from exc


def _coerce_concept_type(concept_type: ConceptType | str) -> ConceptType:
    if isinstance(concept_type, ConceptType):
        return concept_type
    try:
        return ConceptType(concept_type)
    except ValueError as exc:
        raise KnowledgeGraphVocabularyError(f"未知概念类型：{concept_type}") from exc


def normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """逐字符规范化，并保留每个规范化字符在原文中的下标。

    证据区间（span）必须落在**原文**上，而匹配又要在规范化后的文本上做，所以两者要能互相
    换算。逐字符规范化牺牲了跨字符组合（如 `e` + 组合重音）的合并，换来「概念名与正文永远
    用同一套规则」，中文医学术语里不涉及前者。
    """

    chars: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(text):
        produced = unicodedata.normalize("NFKC", character).casefold()
        for item in produced:
            if item.isspace():
                continue
            chars.append(item)
            offsets.append(index)
    return "".join(chars), offsets


def normalize_concept_name(text: str) -> str:
    """规范化概念名/别名，用于匹配。

    与正文走同一个 `normalize_with_offsets`：中文里「肺 癌」与「肺癌」必须匹配到同一个概念，
    所以**内部空白也去掉**；首尾标点再去一层。
    """

    normalized, _ = normalize_with_offsets(text)
    normalized = normalized.strip(_EDGE_PUNCTUATION)
    if not normalized:
        raise KnowledgeGraphVocabularyError(f"概念名规范化后为空：{text!r}")
    return normalized


def allowed_object_types(predicate: GraphClaimPredicate | str) -> frozenset[ConceptType]:
    """抽取规则用：某个 predicate 允许的宾语类型。"""

    return PREDICATE_TYPE_RULES[_coerce_predicate(predicate)][1]


def predicate_label(predicate: GraphClaimPredicate | str) -> str:
    return PREDICATE_LABELS[_coerce_predicate(predicate)]


def validate_triple(
    subject_type: ConceptType | str,
    predicate: GraphClaimPredicate | str,
    object_type: ConceptType | str,
) -> None:
    """校验三元组的两端类型是否属于该 predicate 的允许集合，不合法就抛中文错误。"""

    resolved_predicate = _coerce_predicate(predicate)
    resolved_subject = _coerce_concept_type(subject_type)
    resolved_object = _coerce_concept_type(object_type)
    subject_types, object_types = PREDICATE_TYPE_RULES[resolved_predicate]
    label = PREDICATE_LABELS[resolved_predicate]
    if resolved_subject not in subject_types:
        allowed = "、".join(sorted(member.value for member in subject_types))
        raise KnowledgeGraphVocabularyError(
            f"「{label}」（{resolved_predicate.value}）的主语只能是 {allowed}，"
            f"实际是 {resolved_subject.value}"
        )
    if resolved_object not in object_types:
        allowed = "、".join(sorted(member.value for member in object_types))
        raise KnowledgeGraphVocabularyError(
            f"「{label}」（{resolved_predicate.value}）的宾语只能是 {allowed}，"
            f"实际是 {resolved_object.value}"
        )


def describe_triple(
    subject_name: str, predicate: GraphClaimPredicate | str, object_name: str
) -> str:
    """审核界面用的通俗中文，同时保留原始 predicate 便于核对。"""

    resolved_predicate = _coerce_predicate(predicate)
    return (
        f"{subject_name} ——{PREDICATE_LABELS[resolved_predicate]}——> "
        f"{object_name}（{resolved_predicate.value}）"
    )


def frozen_vocabulary() -> dict[str, list[str]]:
    """导出冻结词表，供文档与测试核对（避免文档与代码各写一份）。"""

    return {
        "conceptTypes": [member.value for member in ConceptType],
        "predicates": [member.value for member in GraphClaimPredicate],
        "claimStatuses": [member.value for member in GraphClaimStatus],
    }