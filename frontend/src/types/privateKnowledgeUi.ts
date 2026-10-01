import { ApiError, getApiErrorMessage } from '../api/http'
import type {
  PrivateKnowledgeDocumentKind,
  PrivateKnowledgeDocumentStatus,
} from './privateKnowledge'

/**
 * 「我的知识库」P1 管理页的界面常量、文案与本地预检。
 *
 * **为什么单独一个文件**：数据层的类型在 `./privateKnowledge.ts`（由 Codex 在实现 P3
 * 咨询接线时落地，2026-10-01）。管理页专用的常量与文案一律放这里，减少双方在同一文件上
 * 互相覆盖；只有「把 TS 类型对齐回后端 schema」（六状态、`parserVersion`/`indexVersion`、
 * 搜索结果类型）时才追加到那个文件，且只增不改。
 *
 * 契约来源：`USER_PRIVATE_KNOWLEDGE_BASE_PLAN.md` §0（K1–K5）、§5、§7、§8.1、§9、§P2；并已按
 * 后端落地代码逐条核对（`backend/app/schemas/private_knowledge.py`、
 * `backend/app/api/routes/private_knowledge.py`，2026-10-01 读，**当时未提交**）：
 * 说明版本字面值、`noticeAccepted`/`noticeVersion` 校验、30 MiB / 100 页上限
 * （`settings.attachment_max_bytes` / `attachment_max_pages`）、文档六状态、
 * `chunkCount` 与 `parserVersion`/`indexVersion`、搜索请求的「1–3 个库 / 1–5 条」限制都对得上。
 *
 * 本页面的全部验证都走 `page.route` 桩，**不代表真实链路已通**。
 */

/**
 * 上传前的一次性说明版本。字面值必须与后端 `routes/private_knowledge.py` 的
 * `NOTICE_VERSION` 完全一致，否则上传会被拒（422 `PRIVATE_KNOWLEDGE_NOTICE_REQUIRED`）。
 */
export const PRIVATE_KNOWLEDGE_NOTICE_VERSION = 'private-knowledge-upload-v1'

/** 每个用户的知识库上限（方案 §5.1 建议 20）。 */
export const PRIVATE_KNOWLEDGE_MAX_COLLECTIONS = 20

/** K1：首版只接这五种文本类文档，**不接图片**（影像判读不在产品边界内）。 */
export const PRIVATE_KNOWLEDGE_ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.pptx', '.txt', '.md'] as const

/** `<input accept>` 用的一行字符串。 */
export const PRIVATE_KNOWLEDGE_ACCEPT = PRIVATE_KNOWLEDGE_ALLOWED_EXTENSIONS.join(',')

/** 与后端 `settings.attachment_max_bytes` 一致（30 MiB）。 */
export const PRIVATE_KNOWLEDGE_MAX_BYTES = 30 * 1024 * 1024

/** 与后端 `settings.attachment_max_pages` 一致（100 页）。 */
export const PRIVATE_KNOWLEDGE_MAX_PAGES = 100

/** 页面上显示的状态文案；六个状态与后端 `PrivateKnowledgeDocumentStatus` 一一对应。 */
export const PRIVATE_KNOWLEDGE_DOCUMENT_STATUS_LABELS: Record<PrivateKnowledgeDocumentStatus, string> = {
  queued: '排队中',
  parsing: '解析中',
  indexing: '建立索引',
  ready: '可用',
  failed: '处理失败',
  deleting: '正在删除',
}

/**
 * 方案 §7 的 8 个受控错误码 + 后端实际上传校验会回的 `PRIVATE_KNOWLEDGE_NOTICE_REQUIRED`。
 *
 * 文案只讲「用户能做什么」，不透传服务端原文、不解释内部实现，也不出现文件名或正文。
 * `PRIVATE_KNOWLEDGE_SELECTION_INVALID` 只会在咨询发送时出现（P3），这里一并映射，
 * 避免以后两处文案分叉。
 */
export const PRIVATE_KNOWLEDGE_ERROR_MESSAGES: Record<string, string> = {
  PRIVATE_KNOWLEDGE_COLLECTION_NOT_FOUND: '这个知识库不存在或已被删除',
  // 后端 409：同名建库 / 同内容文档；404：文档被删或不属于当前账号。
  PRIVATE_KNOWLEDGE_COLLECTION_EXISTS: '已经有同名的知识库，请换个名字',
  PRIVATE_KNOWLEDGE_DOCUMENT_EXISTS: '这个知识库里已经有内容相同的文档',
  PRIVATE_KNOWLEDGE_DOCUMENT_NOT_FOUND: '这份文档不存在或已被删除',
  PRIVATE_KNOWLEDGE_NOTICE_REQUIRED: '上传前请先确认私人资料处理与模型使用说明',
  PRIVATE_KNOWLEDGE_DOCUMENT_UNSUPPORTED:
    '这个文件类型暂不支持：请上传 PDF、Word、PPT、TXT 或 Markdown',
  PRIVATE_KNOWLEDGE_DOCUMENT_TOO_LARGE:
    `文件超过 ${PRIVATE_KNOWLEDGE_MAX_BYTES / 1024 / 1024} MB 上限，请压缩或拆分后再上传`,
  PRIVATE_KNOWLEDGE_PARSE_FAILED: '解析失败，可以重试；扫描件或加密文件可能无法解析',
  PRIVATE_KNOWLEDGE_INDEX_NOT_READY: '还在建立索引，请稍后再试',
  PRIVATE_KNOWLEDGE_SELECTION_INVALID: '选择的知识库无效，请重新选择',
  PRIVATE_KNOWLEDGE_LIMIT_EXCEEDED:
    `数量已达上限（最多 ${PRIVATE_KNOWLEDGE_MAX_COLLECTIONS} 个知识库），请先删除不用的`,
  PRIVATE_KNOWLEDGE_RATE_LIMITED: '操作过于频繁，请稍后再试',
}

/** 本地预检文案：扩展名与体积能在浏览器判，页数与内容结构只能等服务端。 */
export const PRIVATE_KNOWLEDGE_LOCAL_ERRORS = {
  extension: `只支持 ${PRIVATE_KNOWLEDGE_ALLOWED_EXTENSIONS.join(' / ')} 这几种文档，暂不支持图片`,
  tooLarge: `单个文件不能超过 ${PRIVATE_KNOWLEDGE_MAX_BYTES / 1024 / 1024} MB，请压缩或拆分后再上传`,
  noFileName: '这个文件没有可用的文件名，请换一份文件',
} as const

/** 首次上传前一次性说明（K2/K3/K5 与方案 §9 的删除语义）。纯文本，前端不做 Markdown 渲染。 */
export const PRIVATE_KNOWLEDGE_NOTICE_TITLE = '上传到「我的知识库」前请先了解'

export const PRIVATE_KNOWLEDGE_NOTICE_ITEMS = [
  '文档会加密保存，只有你能读取、上传和删除。',
  '只保存解析出的文字与定位，不保存原件，所以之后不能从这里下载原始文件。',
  '保存前会做姓名、电话等规则脱敏，但规则脱敏不能保证去掉全部敏感健康信息。',
  '默认不会把你的资料全文发给云端向量化服务；只有你在咨询里选中这个知识库、并且片段通过相关度门槛后，少量片段才会随问题交给当前聊天模型。',
  '它不会自动用于所有对话，也不会自动写进健康记录；每次咨询都要你自己选。',
  '你随时可以删除单个文档、整个知识库或账号。删除后正文、索引与词项一并清理，历史回答只留一句「私人资料已删除」。',
] as const

/** 已经确认过说明时，上传区只显示这一句短提示。 */
export const PRIVATE_KNOWLEDGE_NOTICE_SHORT =
  '文档会加密存入知识库，只在你于咨询中选中它时才会被检索；不保存原件。'

/** 页面上必须显式出现的作用域提示（方案 §8.1 最后一条）。 */
export const PRIVATE_KNOWLEDGE_SCOPE_HINT =
  '不会自动用于所有对话：要在咨询里选中某个知识库，它才会参与检索。'

/** 方案 §8.1：公共医学知识搜索与私人资料是两回事，界面上不能混。 */
export const PRIVATE_KNOWLEDGE_BOUNDARY_HINT =
  '这里是你自己的资料，不会被当成经过医学审核的公共资料；它只帮你查找、整理和解释，不用于确诊、开药或调整用药。'

/** 文档是否还在处理中（据此决定要不要继续轮询）。`deleting` 由删除流程接管，不轮询。 */
export function isPrivateKnowledgeDocumentPending(status: PrivateKnowledgeDocumentStatus): boolean {
  return status === 'queued' || status === 'parsing' || status === 'indexing'
}

/** 文件类型标签；未知类型退回大写后缀，不猜具体格式。 */
export function privateKnowledgeKindLabel(kind: PrivateKnowledgeDocumentKind | string): string {
  const labels: Record<string, string> = {
    pdf: 'PDF',
    docx: 'Word',
    pptx: 'PPT',
    txt: 'TXT',
    md: 'Markdown',
  }
  return labels[kind] || String(kind).toUpperCase()
}

/**
 * 受控错误文案：优先用受控错误码映射，其它情况沿用全局错误出口
 * （`getApiErrorMessage` 已经做过「不透传结构化内容」的兜底复核）。
 */
export function privateKnowledgeErrorMessage(error: unknown): string {
  if (error instanceof ApiError && PRIVATE_KNOWLEDGE_ERROR_MESSAGES[error.code]) {
    return PRIVATE_KNOWLEDGE_ERROR_MESSAGES[error.code]
  }
  return getApiErrorMessage(error)
}

/**
 * 上传前的本地预检。
 *
 * 只拦**浏览器能确定**的两件事：扩展名和体积。页数、格式真伪、压缩包嵌套、内容能否解析
 * 都由服务端在隔离进程里判断并回受控错误码——前端不假装自己能验，也不把文件内容读进内存。
 */
export function checkPrivateKnowledgeFile(file: File): string {
  const name = (file.name || '').toLowerCase()
  if (!name.includes('.')) return PRIVATE_KNOWLEDGE_LOCAL_ERRORS.noFileName
  if (!PRIVATE_KNOWLEDGE_ALLOWED_EXTENSIONS.some(extension => name.endsWith(extension))) {
    return PRIVATE_KNOWLEDGE_LOCAL_ERRORS.extension
  }
  if (file.size > PRIVATE_KNOWLEDGE_MAX_BYTES) return PRIVATE_KNOWLEDGE_LOCAL_ERRORS.tooLarge
  return ''
}

// ---------------------------------------------------------------------------
// P2：知识库内搜索（`POST /private-knowledge/search`）
//
// 约束照抄后端 `PrivateKnowledgeSearchRequest`：`query` 1–2000（去首尾空白）、
// `collectionIds` 1–3 且不可重复、`limit` 1–5（默认 5）。方案 §P2 明确「只提供受控搜索接口，
// 尚不自动送入模型」，所以这一块只把命中显示给用户，不写进对话、不写进健康记录。
// ---------------------------------------------------------------------------

export const PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS = 3
export const PRIVATE_KNOWLEDGE_SEARCH_MAX_LIMIT = 5
export const PRIVATE_KNOWLEDGE_SEARCH_MAX_QUERY_LENGTH = 2000

/** 搜索区的常驻说明：范围、性质、以及「这一步不会进对话」。 */
export const PRIVATE_KNOWLEDGE_SEARCH_HINT =
  '只在你勾选的知识库里查找；结果是你自己的未核验资料，不等同于公共医学来源。这一步只做检索，不会自动写进对话或健康记录。'

/** 没勾选任何知识库时的说明。 */
export const PRIVATE_KNOWLEDGE_SEARCH_SCOPE_REQUIRED = `请先勾选要检索的知识库（最多 ${PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS} 个）。`

/** 没找到命中时的说明：讲清范围，避免用户以为「所有资料里都没有」。 */
export const PRIVATE_KNOWLEDGE_SEARCH_EMPTY = '在你勾选的知识库里没有找到相关内容。'

/** 命中数量上限说明（后端 limit 最大 5）。 */
export const PRIVATE_KNOWLEDGE_SEARCH_LIMIT_HINT = `最多返回 ${PRIVATE_KNOWLEDGE_SEARCH_MAX_LIMIT} 条命中，按相关度排序。`

/** 相关度只给区间值，不当成概率或医学结论。 */
export function privateKnowledgeSimilarityLabel(similarity: number): string {
  if (!Number.isFinite(similarity)) return '相关度未知'
  const bounded = Math.max(0, Math.min(1, similarity))
  return `相关度 ${Math.round(bounded * 100)}%`
}