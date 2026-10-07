import http, { ApiError } from './http'
import { KNOWLEDGE_GRAPH_MAX_NODES } from '../types/knowledgeGraphUi'

/**
 * 公共医学知识图谱的**只读**客户端。
 *
 * 契约来源（只读核对，未改动后端任何文件）：
 * - `backend/app/api/routes/knowledge_graph.py`（路由与响应字段）
 * - `backend/app/services/knowledge_graph_query.py`（可用性与证据语义）
 * - `backend/docs/API.md` §公共医学知识图谱（只读，默认关闭）
 *
 * 三条必须照实转达的语义：
 * 1. `GET /knowledge-graph/concepts?query=` 只返回「已发布关系」里出现过的概念（最多 5 个），
 *    字段固定为 `{items:[{id,name,type}]}`；**图谱读开关关闭时它同样返回空列表**，
 *    因此「空列表」不能直接当成「图谱里确实没有这个概念」（详见 `knowledgeGraphQuery` 的注释）。
 * 2. `POST /knowledge-graph/explore` 的 `available=false` 明确表示「未启用 / 发布版本失配 /
 *    图谱故障」，文档要求**不得展示成「没有医学关系」**。
 * 3. 每条关系只带 `claimId / subject / object / predicate / evidence`；
 *    `evidence` 是 `{documentId,chunkId,title,section,url}`，**没有正文片段**，
 *    所以本页只能展示「来源文档 + 定位标识」，不得自己编摘要。
 */

/** 概念类型（`ConceptType`，五类，G0 冻结）。 */
export type GraphConceptType = 'topic' | 'symptom' | 'department' | 'red_flag' | 'self_care'

/** 关系类型（`GraphClaimPredicate`，五类，G0 冻结）。本模块不写死请求参数，只用于标注。 */
export type GraphPredicate =
  | 'MAY_INCLUDE_SYMPTOM'
  | 'HAS_RED_FLAG'
  | 'SUGGESTS_DEPARTMENT'
  | 'HAS_SELF_CARE_TOPIC'
  | 'RELATED_TOPIC'

export interface GraphConcept {
  id: string
  name: string
  type: string
}

export interface GraphRelationEndpoint {
  id: string
  name: string
  type: string
}

export interface GraphEvidence {
  documentId: string
  chunkId: string
  title: string
  section: string
  url: string | null
}

export interface GraphRelation {
  claimId: string
  subject: GraphRelationEndpoint
  object: GraphRelationEndpoint
  predicate: string
  evidence: GraphEvidence[]
}

export interface GraphExploreResult {
  /** false = 图谱未启用 / 发布版本失配 / 图谱故障，**不是**「没有关系」。 */
  available: boolean
  revision: number | null
  relations: GraphRelation[]
}

function contractError(message: string): ApiError {
  // 结构不符合契约时**不能**退化成「无结果」，否则就是把「接口坏了」谎报成「图谱里没有」。
  return new ApiError(message, 'GRAPH_CONTRACT_MISMATCH')
}

function readItems(payload: unknown): GraphConcept[] {
  if (typeof payload !== 'object' || payload === null) {
    throw contractError('知识图谱概念接口返回了无法识别的数据')
  }
  const items = (payload as { items?: unknown }).items
  if (!Array.isArray(items)) {
    throw contractError('知识图谱概念接口返回了无法识别的数据')
  }
  return items
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      id: String(item.id ?? ''),
      name: String(item.name ?? ''),
      type: String(item.type ?? ''),
    }))
    .filter(item => item.id !== '' && item.name !== '')
}

function readExplore(payload: unknown): GraphExploreResult {
  if (typeof payload !== 'object' || payload === null) {
    throw contractError('知识图谱关系接口返回了无法识别的数据')
  }
  const record = payload as { available?: unknown; revision?: unknown; relations?: unknown }
  if (typeof record.available !== 'boolean') {
    throw contractError('知识图谱关系接口返回了无法识别的数据')
  }
  const relations = Array.isArray(record.relations) ? record.relations : []
  return {
    available: record.available,
    revision: typeof record.revision === 'number' ? record.revision : null,
    relations: relations.filter(
      (item): item is GraphRelation => typeof item === 'object' && item !== null,
    ),
  }
}

export const knowledgeGraphApi = {
  /** `GET /knowledge-graph/concepts?query=` —— 只有参与已发布关系的概念才会被返回。 */
  async concepts(query: string): Promise<GraphConcept[]> {
    const { data } = await http.get('/knowledge-graph/concepts', { params: { query } })
    return readItems(data)
  },

  /**
   * `POST /knowledge-graph/explore` —— 1 跳只读查询。
   *
   * 刻意**不传** `relationshipTypes`：后端的默认值就是当前冻结的全部关系类型，
   * 前端写死枚举会在后端新增类型时静默漏掉。`depth` 只有 1 是后端硬约束，`maxNodes`
   * 取上限以尽量少截断。
   */
  async explore(conceptId: string): Promise<GraphExploreResult> {
    const { data } = await http.post('/knowledge-graph/explore', {
      conceptId,
      depth: 1,
      maxNodes: KNOWLEDGE_GRAPH_MAX_NODES,
    })
    return readExplore(data)
  },
}

export default knowledgeGraphApi