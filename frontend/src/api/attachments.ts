import http from './http'
import type { Attachment } from '../types/consultations'

/**
 * 后端要求每次上传都带上说明版本，不带就返回 422 `DOCUMENT_NOTICE_REQUIRED`。
 * 说明文字在前端弹一次、之后本机记住，但字段每次都要发——服务端据此写一条 consent 审计。
 */
export const DOCUMENT_NOTICE_VERSION = 'document-upload-v1'

/** 图片上传的说明版本，契约固定值；服务端据此写 consent 审计。 */
export const IMAGE_NOTICE_VERSION = 'medical-image-upload-v1'

/**
 * 上传要等服务端解析整份文档、识别图片要等视觉模型返回，所以客户端超时必须**明显长于**
 * 服务端处理上限（`ATTACHMENT_PARSE_TIMEOUT_SECONDS`，2026-09-21 由 30 秒放宽到 60 秒），
 * 否则会出现「服务端还在处理、客户端已经超时」的假失败。
 */
const LONG_REQUEST_TIMEOUT_MS = 120_000

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
      { timeout: LONG_REQUEST_TIMEOUT_MS },
    )).data
  },
  /**
   * 上传图片走独立接口（契约 `POST /consultations/{id}/images`）。只传**一张**：
   * 逐张上传才能让「某一张被拒」不影响同批的其它图片。
   *
   * 2026-09-22 起 multipart 里**不再有 `imageCategory`**（契约第 10.2 节）：类别由服务端固定的
   * 视觉模型自动判断，响应里的 `imageCategory` 才是事实，前端只负责如实展示。
   */
  async uploadImage(consultationId: string, file: File) {
    const data = new FormData()
    data.append('file', file)
    data.append('noticeAccepted', 'true')
    data.append('noticeVersion', IMAGE_NOTICE_VERSION)
    return (await http.post<Attachment>(
      `/consultations/${consultationId}/images`,
      data,
      { timeout: LONG_REQUEST_TIMEOUT_MS },
    )).data
  },
  /**
   * 取规范化图片的字节。鉴权接口，没有公开 URL，也不能跨用户读。
   *
   * 到期时服务端返回 `410 IMAGE_EXPIRED`；但 `responseType: 'blob'` 下错误体也是 Blob，
   * 通用的 `sanitizeApiMessage` 读不到 `code`，所以调用方要**按 HTTP 状态 410 判断到期**。
   */
  async content(attachmentId: string) {
    return (await http.get<Blob>(`/attachments/${attachmentId}/content`, {
      responseType: 'blob',
      timeout: LONG_REQUEST_TIMEOUT_MS,
    })).data
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