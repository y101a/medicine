import http from './http'
import { ApiError } from './http'
import type { AnswerFormat, Consultation, Message, Page } from '../types/consultations'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL?.trim() || '/api/v1').replace(/\/$/, '')

export interface RetrievalProgress {
  status: 'completed' | 'empty' | 'failed' | 'skipped'
  gateReason: 'medical_content' | 'non_medical_content' | 'emergency'
  webSearchStatus: 'completed' | 'empty' | 'failed' | 'skipped'
  coverageLimited?: boolean
  errorCode?: string | null
  webSearchErrorCode?: string | null
}

async function streamAnswer(
  id: string,
  clientRequestId: string,
  modelId: string,
  answerFormat: AnswerFormat,
  signal: AbortSignal,
  onDelta: (content: string) => void,
  onRetrieval: (progress: RetrievalProgress) => void,
  sourceMessageId?: string,
  retried = false,
): Promise<Message> {
  const response = await fetch(`${apiBaseUrl}/consultations/${id}/stream`, {
    method: 'POST',
    credentials: 'include',
    signal,
    headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
    body: JSON.stringify({ clientRequestId, modelId, answerFormat, sourceMessageId }),
  })
  if (response.status === 401 && !retried) {
    await http.post('/auth/refresh')
    return streamAnswer(
      id,
      clientRequestId,
      modelId,
      answerFormat,
      signal,
      onDelta,
      onRetrieval,
      sourceMessageId,
      true,
    )
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { code?: string; message?: string }
    throw new ApiError(payload.message || 'AI 服务请求失败', payload.code || `HTTP_${response.status}`, response.status)
  }
  if (!response.body) throw new ApiError('浏览器无法读取流式回答', 'STREAM_UNAVAILABLE')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed: Message | undefined
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.trim()) continue
      const event = JSON.parse(line) as {
        type: 'start' | 'delta' | 'done' | 'error'
        content?: string
        message?: Message
        code?: string
        messageText?: string
        retrieval?: RetrievalProgress
      } & Record<string, unknown>
      if (event.type === 'start' && event.retrieval) onRetrieval(event.retrieval)
      if (event.type === 'delta' && event.content) onDelta(event.content)
      if (event.type === 'done' && event.message) completed = event.message
      if (event.type === 'error') {
        const text = typeof event.message === 'string' ? event.message : 'AI 回答生成失败'
        throw new ApiError(text, event.code || 'AI_GENERATION_FAILED')
      }
    }
    if (done) break
  }
  if (!completed) throw new ApiError('AI 回答意外中断，请稍后重试', 'STREAM_INCOMPLETE')
  return completed
}

export const consultationsApi = {
  async create(clientRequestId: string) {
    return (await http.post<Consultation>('/consultations', { clientRequestId })).data
  },
  async list(offset = 0) {
    return (await http.get<Page<Consultation>>('/consultations', { params: { offset, limit: 20 } })).data
  },
  async get(id: string) {
    return (await http.get<Consultation>(`/consultations/${id}`)).data
  },
  async messages(id: string, before?: number) {
    return (await http.get<Page<Message>>(`/consultations/${id}/messages`, { params: { before, limit: 50 } })).data
  },
  async send(id: string, content: string, clientRequestId: string) {
    return (await http.post<Message>(`/consultations/${id}/messages`, { content, clientRequestId })).data
  },
  stream: streamAnswer,
  async remove(id: string) { await http.delete(`/consultations/${id}`) },
}
