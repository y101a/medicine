import http from './http'
import type { AiModel } from '../types/consultations'

export const modelsApi = {
  async list() {
    return (await http.get<{ items: AiModel[] }>('/models')).data.items
  },
}
