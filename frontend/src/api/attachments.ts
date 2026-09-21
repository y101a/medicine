import http from './http'
import type { Attachment } from '../types/consultations'

/**
 * 后端要求每次上传都带上说明版本，不带就返回 422 `DOCUMENT_NOTICE_REQUIRED`。
 * 说明文字在前端弹一次、之后本机记住，但字段每次都要发——服务端据此写一条 consent 审计。
 */
export const DOCUMENT_NOTICE_VERSION = 'document-upload-v1'

/**
 * 上传要等服务端解析整份文档，所以客户端超时必须**明显长于**服务端解析上限
 * （`ATTACHMENT_PARSE_TIMEOUT_SECONDS`，2026-09-21 由 30 秒放宽到 60 秒），
 * 否则会出现「服务端还在解析、客户端已经超时」的假失败。
 */
const UPLOAD_TIMEOUT_MS = 120_000

export const attachmentsApi = {
  /** 上传挂在会话下：调用方必须先确保有 `consultation_id`（见 HomeView 的静默建会话）。 */
  async upload(consultationId: string, file: File) {
    const data = new FormData()
    data.append('file', file)
    data.append('noticeAccepted', 'true')
    data.append('noticeVersion', DOCUMENT_NOTICE_VERSION)
    return (await http.post<Attachment>(
      `/consultations/${consultationId}/attachments`,
      data,
      { timeout: UPLOAD_TIMEOUT_MS },
    )).data
  },
  async list(consultationId: string) {
    return (await http.get<{ items: Attachment[] }>(
      `/consultations/${consultationId}/attachments`,
    )).data.items
  },
  /** 永久删除：原件本就没保存，这里删的是加密文字分块。 */
  async remove(attachmentId: string) {
    await http.delete(`/attachments/${attachmentId}`)
  },
}