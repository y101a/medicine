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
  followUp?: FollowUpCard | null
  triage?: TriageResult | null
  citations?: MessageCitation[]
  attachments?: MessageAttachment[]
  createdAt: string
}

/** 后端接受这五种病历文档（按文件名扩展名判定），以及图片。 */
export type AttachmentKind = 'pdf' | 'docx' | 'pptx' | 'txt' | 'md' | 'image'

/**
 * 图片类别，上传时由用户自己选。后端把它当作**处理提示**而不是可信事实：
 * 三类都不输出疾病判断，差别只在能读到什么、以及给出哪段能力边界文案。
 */
/** 服务端自动分类的四类可保存图片（`unclear` 会被拒绝，前端收不到）。 */
export type ImageCategory = 'report' | 'medical_imaging' | 'body_photo' | 'unrelated'

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
