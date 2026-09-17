import http from './http'
import type {
  HealthRecord,
  HealthRecordCreateRequest,
  HealthRecordExtractRequest,
  HealthRecordSettings,
  HealthRecordSettingsRequest,
  HealthRecordUpdateRequest,
  OnboardingStatus,
} from '../types/healthRecords'

export const healthRecordsApi = {
  async list() {
    return (await http.get<{ items: HealthRecord[] }>('/health-records')).data.items
  },

  async create(payload: HealthRecordCreateRequest) {
    return (await http.post<HealthRecord>('/health-records', payload)).data
  },

  async update(id: string, payload: HealthRecordUpdateRequest) {
    return (await http.patch<HealthRecord>(`/health-records/${id}`, payload)).data
  },

  async remove(id: string) {
    await http.delete(`/health-records/${id}`)
  },

  async settings() {
    return (await http.get<HealthRecordSettings>('/health-records/settings')).data
  },

  async updateSettings(payload: HealthRecordSettingsRequest) {
    return (await http.patch<HealthRecordSettings>('/health-records/settings', payload)).data
  },

  async onboarding(status: OnboardingStatus, note?: string) {
    return (await http.post<HealthRecordSettings>('/health-records/onboarding', {
      status,
      note,
    })).data
  },

  /** 尽力而为的增量更新：失败不打断对话，也不向用户报错。 */
  async extract(payload: HealthRecordExtractRequest) {
    return (await http.post<{ stored: number }>('/health-records/extract', payload)).data
  },
}

export default healthRecordsApi