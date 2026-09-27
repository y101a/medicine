import http from './http'
import type {
  DocumentGeneration,
  DocumentGenerationRequest,
} from '../types/documentGenerations'

/**
 * 生成说明的版本号（契约固定值）。服务端据此写一条 consent 审计；
 * 不带或版本不符返回 422 `DOCUMENT_GENERATION_NOTICE_REQUIRED`。
 */
export const DOCUMENT_GENERATION_NOTICE_VERSION = 'document-generation-v1'

/** 创建任务只等服务端受理（成功是 202，真正生成在后台 worker），所以超时不看生成耗时。 */
const CREATE_TIMEOUT_MS = 60_000

/** 查询只是读任务状态，但 worker 可能正在写库，给比默认 15 秒更宽的上限。 */
const POLL_TIMEOUT_MS = 30_000

/** 下载要读密文、解密、重组响应；单个文件上限 10 MiB（方案 §2.3），给宽松上限。 */
const CONTENT_TIMEOUT_MS = 60_000

/**
 * PPT/Word 文档生成接口（契约 §5.1–§5.4 冻结，前端只按契约调用）：
 * 不打开后端存储路径、不缓存文件字节到本地存储、不接触模型 Key。
 */
export const documentGenerationsApi = {
  async create(consultationId: string, payload: DocumentGenerationRequest) {
    return (await http.post<DocumentGeneration>(
      `/consultations/${consultationId}/document-generations`,
      payload,
      { timeout: CREATE_TIMEOUT_MS },
    )).data
  },
  /** 单个任务状态；轮询用。 */
  async get(id: string) {
    return (await http.get<DocumentGeneration>(`/document-generations/${id}`, {
      timeout: POLL_TIMEOUT_MS,
    })).data
  },
  /** 该会话的全部任务；刷新或切换会话后按 `sourceMessageId` 挂回对应用户消息。 */
  async list(consultationId: string) {
    return (await http.get<{ items: DocumentGeneration[] }>(
      `/consultations/${consultationId}/document-generations`,
      { timeout: POLL_TIMEOUT_MS },
    )).data.items
  },
  /**
   * 取成品字节（契约 §5.3）。鉴权接口、仅所属用户可读；服务端带 `no-store` 与 `nosniff`。
   *
   * 未完成返回 `409 DOCUMENT_GENERATION_NOT_READY`，过期返回 `410 GENERATED_DOCUMENT_EXPIRED`。
   * 注意 `responseType: 'blob'` 下错误体也是 Blob，通用 `sanitizeApiMessage` 读不到 `code`，
   * 所以调用方要**按 HTTP 状态判断**（与配图、附件图片同一条经验）。
   */
  async content(generationId: string, fileId: string) {
    return (await http.get<Blob>(
      `/document-generations/${generationId}/files/${fileId}/content`,
      { responseType: 'blob', timeout: CONTENT_TIMEOUT_MS },
    )).data
  },
  /** 删除：已完成是永久删除，未完成只标记取消（已发生的模型费用不承诺撤销）。 */
  async remove(id: string) {
    await http.delete(`/document-generations/${id}`)
  },
}