export type HealthRecordCategory =
  | 'general_status'
  | 'symptom'
  | 'condition'
  | 'medication'
  | 'allergy'
  | 'lifestyle'
  | 'measurement'
  | 'care_seeking'
  | 'other'

export type HealthRecordSource = 'onboarding' | 'conversation' | 'user'

export type OnboardingStatus = 'good' | 'fair' | 'poor' | 'unsure'

export interface HealthRecord {
  id: string
  category: HealthRecordCategory
  categoryLabel: string
  content: string
  source: HealthRecordSource
  recordedAt: string
  updatedAt: string
}

export interface HealthRecordSettings {
  collectionEnabled: boolean
  noticeSeen: boolean
  recordCount: number
}

export interface HealthRecordCreateRequest {
  category: HealthRecordCategory
  content: string
}

export interface HealthRecordUpdateRequest {
  category?: HealthRecordCategory
  content?: string
}

export interface HealthRecordSettingsRequest {
  collectionEnabled?: boolean
  noticeSeen?: boolean
}

export interface HealthRecordExtractRequest {
  consultationId: string
  /** 该轮助手回答的消息 id：医疗内容判定记录在助手消息上，后端据此回溯用户提问。 */
  messageId: string
}