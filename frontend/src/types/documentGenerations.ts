/**
 * PPT/Word 医学科普文档生成的前端契约类型。
 *
 * 来源：`PPT_WORD_PLAN.md` 第 5 节（冻结 API 契约）、第 8 节（前端实现）、第 2.3 节（默认规模）。
 * 与配图同一套原则：字段都是**服务端返回的事实**，前端不推断任务状态、不拼存储路径、不接触模型 Key，
 * 也不拿主题原文去拼下载文件名。
 */

/** v1 只允许两种格式；`.docm`/`.pptm`/PDF/Excel 都不在范围内（方案 §2.2）。 */
export type DocumentFormat = 'docx' | 'pptx'

/** 任务状态机（契约 §5.2）。前三个是「还在生成」，需要轮询；其余都是终态。 */
export type DocumentGenerationStatus =
  | 'queued'
  | 'generating'
  | 'rendering'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'expired'

/**
 * 创建任务的请求体（契约 §5.1）。
 *
 * 主题与格式**只能**由服务端从 `sourceMessageId` 的原文重新解析：前端不传隐藏 prompt、
 * 不传格式覆盖值，也不传来源列表。
 */
export interface DocumentGenerationRequest {
  /** 幂等键：同一用户、同一值必须返回原任务，绝不重复调用模型（契约 §5.1、方案 §9.2）。 */
  clientRequestId: string
  /** 触发过文档意图的那条用户消息（契约 §5.1）。 */
  sourceMessageId: string
  noticeAccepted: true
  noticeVersion: string
}

/** 单个成品文件（契约 §5.2）。 */
export interface DocumentGenerationFile {
  id: string
  format: DocumentFormat
  mimeType: string
  byteSize: number
  /** PPTX 是幻灯片页数；DOCX 拿不到准确页数时服务端给 null。 */
  pageCount: number | null
  /** 为 false 时不要请求内容接口（会拿到 409）。 */
  available: boolean
}

/** 文档生成任务（契约 §5.1 响应 / §5.2 查询）。 */
export interface DocumentGeneration {
  id: string
  sourceMessageId: string
  status: DocumentGenerationStatus
  /** 用户明确要求的格式；**两种格式仍是一个任务**（方案 §8.2）。 */
  formats: DocumentFormat[]
  /** 完成后才有标题（密文保存，服务端解密后返回；前端从不保存标题明文）。 */
  title: string | null
  /** 服务端固定模型，只用于展示，前端不能改，也不出现在聊天模型下拉框里（方案 §7.2）。 */
  model: string
  /** 只有 `completed` 才可能非空（契约 §5.2）。 */
  files: DocumentGenerationFile[]
  /** 实际使用的来源条数（契约 §5.2）。 */
  sourceCount: number
  /**
   * 失败时的**受控错误码**（服务端只回码，不回模型原文或内部堆栈）。
   * 刷新恢复时用它把「生成失败」还原成一句人能读的原因。
   */
  errorCode?: string | null
  /** 成品保留到期时间；`null` 表示尚未生成（方案 §0.6：加密保存 30 天）。 */
  expiresAt: string | null
  createdAt: string
  updatedAt: string
}

export const DOCUMENT_FORMAT_LABELS: Record<DocumentFormat, string> = {
  docx: 'Word 文档',
  pptx: 'PPT 演示文稿',
}

export const DOCUMENT_FORMAT_EXTENSIONS: Record<DocumentFormat, string> = {
  docx: '.docx',
  pptx: '.pptx',
}

export const DOCUMENT_GENERATION_STATUS_LABELS: Record<DocumentGenerationStatus, string> = {
  queued: '已排队',
  generating: '正在整理内容',
  rendering: '正在排版文件',
  completed: '已生成',
  failed: '生成失败',
  cancelled: '已取消',
  expired: '已过期',
}

/** 还在生成、需要继续轮询的状态。 */
export const DOCUMENT_GENERATION_ACTIVE_STATUSES: DocumentGenerationStatus[] = [
  'queued',
  'generating',
  'rendering',
]

/** 成品保留期（方案 §0.6，用户 2026-09-27 已确认：加密保存 30 天，可提前永久删除）。 */
export const DOCUMENT_GENERATION_RETENTION_DAYS = 30

/**
 * 任务卡必须显示的边界声明（方案 §8.2：必须清楚显示「AI 生成的健康科普资料」，
 * 不能伪装成医院或医生签发的文件）。这一句同时对应《标识办法》第四条(一)的文本显式标识要求。
 */
export const DOCUMENT_GENERATION_DISCLAIMER =
  'AI 生成的健康科普资料｜不作诊断依据。内容由 AI 根据当前知识库整理，可能存在遗漏或错误，不能替代医生面诊；如有不适请及时就医。'

/**
 * 首次说明的固定原文（方案 §8.2 要求逐项包含：AI 依据知识库生成 / 可能遗漏或错误 /
 * 仅作健康科普、不作诊断处方治疗依据 / 可能产生模型费用 / 到期删除）。
 */
export const DOCUMENT_GENERATION_NOTICE_TEXT =
  '内容由 AI 根据当前知识库生成，可能存在遗漏或错误，仅作健康科普，不作诊断、处方或治疗依据；'
  + `生成可能产生模型费用；文件将在 ${DOCUMENT_GENERATION_RETENTION_DAYS} 天后自动删除。`

/**
 * 下载文件名固定为 `AI医学科普-YYYYMMDD.<ext>`：**不拼接用户主题、姓名或其他隐私文本**
 * （契约 §5.3；与配图 `AI科普配图-YYYYMMDD.webp` 同一条经验）。
 */
export function documentDownloadName(format: DocumentFormat, createdAt: string): string {
  const created = new Date(createdAt)
  const stamp = Number.isNaN(created.getTime())
    ? 'unknown'
    : `${created.getFullYear()}${String(created.getMonth() + 1).padStart(2, '0')}${String(created.getDate()).padStart(2, '0')}`
  return `AI医学科普-${stamp}${DOCUMENT_FORMAT_EXTENSIONS[format]}`
}