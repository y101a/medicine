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

/** 后端只接受这五种病历文档；判定以文件名扩展名为准。 */
export type AttachmentKind = 'pdf' | 'docx' | 'pptx' | 'txt' | 'md'

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
