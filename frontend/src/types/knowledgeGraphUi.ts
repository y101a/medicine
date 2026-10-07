import type { GraphRelation } from '../api/knowledgeGraph'

/**
 * 知识图谱探索页的纯展示层：三类文案常量、中文标签与几个可单测的纯函数。
 *
 * 刻意与 `api/knowledgeGraph.ts` 分开：单测会把接口模块整体 mock 掉，
 * 常量与纯函数若和接口放在一起，测试里就会变成 `undefined`（本仓库既有做法，见
 * `types/privateKnowledgeUi.ts`）。
 */

/** 页面三态 + 未搜索 + 查询中。`data-state` 用的就是这里的取值。 */
export type KnowledgeGraphViewState = 'idle' | 'loading' | 'unavailable' | 'empty' | 'ready'

/*
 * 下面几个数字是与后端契约对齐的界面常量。放在本模块（而不是 `api/knowledgeGraph.ts`）
 * 是因为单测会把接口模块整体 mock 掉，常量跟着接口走就会在测试里变成 `undefined`。
 */

/** 搜索词长度限制：后端 `Query(min_length=2, max_length=50)` 与规范化后的长度一致。 */
export const KNOWLEDGE_GRAPH_QUERY_MIN_LENGTH = 2
export const KNOWLEDGE_GRAPH_QUERY_MAX_LENGTH = 50

/** 后端 `GraphExploreIn.max_nodes` 上限（也是 `MAX_GRAPH_CLAIMS`）。 */
export const KNOWLEDGE_GRAPH_MAX_NODES = 30

/** 单次 explore 最多返回 `max_nodes - 1` 条关系（路由按 `max_nodes - 1` 截断）。 */
export const KNOWLEDGE_GRAPH_MAX_RELATIONS = KNOWLEDGE_GRAPH_MAX_NODES - 1

/**
 * 医学边界（必须常驻页面，不是弹窗式的一次性提示）。
 *
 * 本页只呈现后端已有的结构化数据与证据：不生成结论、不给剂量、不推荐药名、不说确诊。
 */
export const KNOWLEDGE_GRAPH_DISCLAIMER =
  '本页只展示后端知识图谱里已发布的公共科普关系与其来源证据，全部内容未经医学审核，'
  + '仅供健康科普参考，不构成诊断、检查或用药建议，也不能替代医生的判断；'
  + '身体不适请及时就医，紧急情况请拨打 120。'

/** 关系卡片上的短提示也复用同一口径。 */
export const KNOWLEDGE_GRAPH_BOUNDARY_SHORT =
  '本页不做诊断、不给用药建议、不替代医生。'

/** 未审核 / 未发布关系的固定标注（用户 2026-10-07 明确要求的口径）。 */
export const KNOWLEDGE_GRAPH_UNREVIEWED_NOTICE = '未审核、仅供参考、不是医学结论'

/** 查询失败时对「图谱不可用」的解释，明确区别于「没有找到」。 */
export const KNOWLEDGE_GRAPH_UNAVAILABLE_HINT =
  '图谱接口这次没有返回可用数据，这不等于「没有相关概念」；稍后重试，或先去工作区用其他方式了解。'

/** 空结果的建议。 */
export const KNOWLEDGE_GRAPH_EMPTY_HINT =
  '可以换一个更常见的说法再试（例如症状名、主题名或科室名），也可以点下面的示例。'

/**
 * 空结果时的诚实补充。
 *
 * `find_public_concepts` 在 `neo4j_read_enabled=false` 时**直接返回空列表**，
 * 所以「空」既可能是真的没有匹配，也可能是图谱读取开关没打开。界面不能只讲一半。
 */
export const KNOWLEDGE_GRAPH_EMPTY_CAVEAT =
  '另外说明：图谱读取开关关闭时，这个接口同样只会返回空列表，'
  + '因此「没有找到」并不等于图谱里确实没有相关概念。'

/** 空态示例关键词：取自仓库里已登记的候选主题，不涉及剂量、药名推荐或确诊口径。 */
export const KNOWLEDGE_GRAPH_EXAMPLE_QUERIES = ['发热', '儿童发热', '科学运动', '抗菌药物']

/** 关系类型的中文标签（`GraphClaimPredicate` 五类）。 */
export const GRAPH_PREDICATE_LABELS: Record<string, string> = {
  MAY_INCLUDE_SYMPTOM: '可能出现的表现',
  HAS_RED_FLAG: '需要警惕的红旗提醒',
  SUGGESTS_DEPARTMENT: '通常咨询的科室',
  HAS_SELF_CARE_TOPIC: '自我照护主题',
  RELATED_TOPIC: '相关主题',
}

/** 分组顺序：固定按「表现 → 红旗 → 科室 → 自我照护 → 相关主题」展示，避免每次刷新跳序。 */
export const GRAPH_PREDICATE_ORDER = [
  'MAY_INCLUDE_SYMPTOM',
  'HAS_RED_FLAG',
  'SUGGESTS_DEPARTMENT',
  'HAS_SELF_CARE_TOPIC',
  'RELATED_TOPIC',
] as const

/** 概念类型的中文标签（`ConceptType` 五类）。 */
export const GRAPH_CONCEPT_TYPE_LABELS: Record<string, string> = {
  topic: '主题',
  symptom: '症状',
  department: '科室',
  red_flag: '红旗提醒',
  self_care: '自我照护',
}

export function predicateLabel(predicate: string): string {
  return GRAPH_PREDICATE_LABELS[predicate] ?? predicate
}

export function conceptTypeLabel(type: string): string {
  return GRAPH_CONCEPT_TYPE_LABELS[type] ?? type
}

export interface KnowledgeGraphRelationGroup {
  predicate: string
  label: string
  /** false = 后端返回了本页未登记的关系类型（照实展示，不隐藏、不改名）。 */
  known: boolean
  relations: GraphRelation[]
}

/**
 * 按关系类型分组。
 *
 * 已知类型按 `GRAPH_PREDICATE_ORDER` 排序；未知类型排在后面并标记 `known: false`，
 * 因为「后端扩展了枚举」和「前端漏渲染」必须能区分开。
 */
export function groupRelationsByPredicate(
  relations: readonly GraphRelation[],
): KnowledgeGraphRelationGroup[] {
  const buckets = new Map<string, GraphRelation[]>()
  for (const relation of relations) {
    const predicate = typeof relation?.predicate === 'string' ? relation.predicate : ''
    const key = predicate || 'UNKNOWN'
    const bucket = buckets.get(key)
    if (bucket) bucket.push(relation)
    else buckets.set(key, [relation])
  }
  const known = GRAPH_PREDICATE_ORDER.filter(predicate => buckets.has(predicate))
  const unknown = [...buckets.keys()].filter(
    key => !(GRAPH_PREDICATE_ORDER as readonly string[]).includes(key),
  )
  return [...known, ...unknown.sort()].map(predicate => ({
    predicate,
    label: predicateLabel(predicate),
    known: (GRAPH_PREDICATE_ORDER as readonly string[]).includes(predicate),
    relations: buckets.get(predicate) ?? [],
  }))
}

/** 契约里没有审核字段；若后端未来加上，只有这些取值才算「已审核 + 已发布」。 */
const REVIEWED_VALUES = new Set(['published', 'approved', 'reviewed'])

export interface RelationReviewState {
  reviewed: boolean
  /** 后端若返回了审核字段，原样带出来供界面标注；没有则为 null。 */
  raw: string | null
}

/**
 * 一条关系是否已审核。
 *
 * 后端契约**只返回** `status=published`、`review_decision=approved` 且有有效证据的关系
 * （`backend/app/services/knowledge_graph_query.py` 的 `explore_public_graph` 逐条校验），
 * 所以「没有审核字段」按已审核处理。这里仍然读一遍可选字段：一旦后端把未审核/未发布关系
 * 放进响应，本页必须显著标注「未审核、仅供参考、不是医学结论」，绝不能当成事实陈述。
 */
export function readRelationReview(relation: unknown): RelationReviewState {
  if (typeof relation !== 'object' || relation === null) return { reviewed: true, raw: null }
  const record = relation as Record<string, unknown>
  const values = [record.status, record.reviewStatus, record.reviewDecision].filter(
    (value): value is string => typeof value === 'string' && value.trim() !== '',
  )
  if (!values.length) return { reviewed: true, raw: null }
  const normalized = values.map(value => value.trim().toLowerCase())
  return {
    reviewed: normalized.every(value => REVIEWED_VALUES.has(value)),
    raw: normalized.join(' / '),
  }
}

/** 只给 http/https 生成可点击链接：证据里的 url 来自后端，不能假设它一定是安全协议。 */
export function isHttpUrl(value: unknown): value is string {
  return typeof value === 'string' && /^https?:\/\//i.test(value.trim())
}