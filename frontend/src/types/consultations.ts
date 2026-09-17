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
  createdAt: string
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
}
