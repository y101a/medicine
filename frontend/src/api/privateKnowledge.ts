import http from './http'
import type {
  PrivateKnowledgeCollection,
  PrivateKnowledgeDocument,
} from '../types/privateKnowledge'

export const PRIVATE_KNOWLEDGE_NOTICE_VERSION = 'private-knowledge-upload-v1'

export const privateKnowledgeApi = {
  async collections() {
    return (await http.get<{ items: PrivateKnowledgeCollection[] }>('/private-knowledge/collections')).data.items
  },
  async createCollection(name: string, description?: string) {
    return (await http.post<PrivateKnowledgeCollection>('/private-knowledge/collections', {
      name,
      description: description || null,
    })).data
  },
  async updateCollection(id: string, name: string, description?: string) {
    return (await http.patch<PrivateKnowledgeCollection>(`/private-knowledge/collections/${id}`, {
      name,
      description: description || null,
    })).data
  },
  async removeCollection(id: string) {
    await http.delete(`/private-knowledge/collections/${id}`)
  },
  async documents(collectionId: string) {
    return (await http.get<{ items: PrivateKnowledgeDocument[] }>(
      `/private-knowledge/collections/${collectionId}/documents`,
    )).data.items
  },
  /**
   * 单文档状态：处理中的文档按它逐个轮询，不整表重拉。
   * 由 DSH 为 P1 管理页**追加**（其余方法一行未动）。
   */
  async getDocument(id: string) {
    return (await http.get<PrivateKnowledgeDocument>(
      `/private-knowledge/documents/${id}`,
    )).data
  },
  async upload(collectionId: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    form.append('noticeAccepted', 'true')
    form.append('noticeVersion', PRIVATE_KNOWLEDGE_NOTICE_VERSION)
    return (await http.post<PrivateKnowledgeDocument>(
      `/private-knowledge/collections/${collectionId}/documents`,
      form,
      { timeout: 120_000 },
    )).data
  },
  async retryDocument(id: string) {
    return (await http.post<PrivateKnowledgeDocument>(
      `/private-knowledge/documents/${id}/retry`,
    )).data
  },
  async removeDocument(id: string) {
    await http.delete(`/private-knowledge/documents/${id}`)
  },
}
