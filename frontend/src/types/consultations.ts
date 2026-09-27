export interface Consultation {
  id: string
  title: string
  messageCount: number
  createdAt: string
  updatedAt: string
}
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sequence: number
  provider?: string | null
  modelId?: string | null
  modelName?: string | null
  generationStatus?: 'completed' | 'stopped' | 'failed' | null
  answerFormat?: 'plain' | 'card'
  medicalContent?: boolean
  sourceMessageId?: string | null
  /**
   * 服务端本地意图判定：用户消息里同时出现「主动生成动作 + 图片对象 + 医学主题」才为 true
   * （否定请求、普通文生图、仅询问功能、带附件或紧急分流都为 false，见
   * `backend/app/services/image_generation_intent.py`）。
   *
   * 命中时前端**不再调用 `/stream`**，直接以这条用户消息为来源创建科普配图任务。
   */
  imageGenerationIntent?: boolean
  /**
   * 服务端本地意图判定：用户消息里同时出现「生成动作 + 明确格式（PPT/演示文稿/幻灯片 或
   * Word/DOCX/文档）+ 医学主题」才为 true（否定请求、仅询问功能、非医学主题、缺格式、
   * 带附件或紧急分流都为 false，见 `backend/app/services/document_generation_intent.py`）。
   *
   * 命中时前端**不再调用 `/stream`**，直接以这条用户消息为来源创建文档生成任务；
   * 缺格式时故意不命中——由普通聊天先问清格式，避免意外产生费用（方案 §3）。
   */
  documentGenerationIntent?: boolean
  followUp?: FollowUpCard | null
  triage?: TriageResult | null
  citations?: MessageCitation[]
  attachments?: MessageAttachment[]
  createdAt: string
}

/** 后端接受这五种病历文档（按文件名扩展名判定），以及图片。 */
export type AttachmentKind = 'pdf' | 'docx' | 'pptx' | 'txt' | 'md' | 'image'

/**
 * 图片类别**由服务端固定的视觉模型判定**（2026-09-22 起前端不再手选），前端只如实展示：
 * 上传时传 `imageCategory` 会被忽略，响应里的 `imageCategory` 才是事实。
 * 各类都不输出疾病判断，差别只在能读到什么、以及给出哪段能力边界文案。
 * `unclear` 会被服务端拒绝，前端收不到；其余五类都会保存成图片附件。
 */
export type ImageCategory =
  | 'report'
  | 'medical_imaging'
  | 'body_photo'
  | 'unrelated'
  | 'medication_leaflet'

/** 上传并解析成功的文档（原件不保存，只留加密文字）。 */
export interface Attachment {
  id: string
  displayName: string
  kind: AttachmentKind
  byteSize: number
  pageCount?: number | null
  charCount: number
  preview: string
  status: 'ready'
  createdAt: string
  /** 以下字段只有图片附件有值；`mimeType` 是后端规范化后的类型（无元数据 WebP）。 */
  imageCategory?: ImageCategory | null
  mimeType?: string | null
  width?: number | null
  height?: number | null
  /** 规范化图片是否还在 90 天保留期内；为 false 时字节已被清理，只能看识别文字。 */
  imageAvailable?: boolean | null
  imageExpiresAt?: string | null
}

/**
 * 挂在消息上的附件引用。文档被删除后后端保留一条墓碑（`id` 置空、`status: 'deleted'`），
 * 历史消息里要显示「已删除」，而不是让附件凭空消失。
 */
export interface MessageAttachment {
  id?: string | null
  displayName: string
  kind?: AttachmentKind | null
  status: 'ready' | 'deleted'
  /** 图片附件才有：类别、是否还在保留期内、到期时间。 */
  imageCategory?: ImageCategory | null
  imageAvailable?: boolean | null
  imageExpiresAt?: string | null
}

export interface MessageCitation {
  referenceNumber?: number | null
  sourceKey: string
  organization: string
  title: string
  canonicalUrl: string
  sectionTitle?: string | null
  similarity: number
  trustLevel: 'approved' | 'prototype'
}

export interface TriageResult {
  level: 'emergency'
  ruleVersion?: string
  assessmentMethod?: 'deterministic_rules'
  title: string
  summary: string
  reasons: string[]
  actions: string[]
  ruleIds: string[]
  assessedAt: string
}

export type FollowUpQuestionType = 'single_choice' | 'multiple_choice' | 'scale' | 'text'
export interface FollowUpOption { value: string; label: string }
export interface FollowUpQuestion {
  id: string
  label: string
  type: FollowUpQuestionType
  required: boolean
  options: FollowUpOption[]
  min?: number | null
  max?: number | null
}
export interface FollowUpCard { intro: string; questions: FollowUpQuestion[] }
export type FollowUpAnswers = Record<string, string | string[] | number>
export type AnswerFormat = 'plain' | 'card'
export interface Page<T> { items: T[]; hasMore: boolean }

export interface AiModel {
  id: string
  name: string
  provider: string
  providerName: string
  description: string
  isDefault: boolean
  /** 该模型的密钥来自本站（server）还是用户自己配置的（user）。 */
  keySource: 'server' | 'user'
}
