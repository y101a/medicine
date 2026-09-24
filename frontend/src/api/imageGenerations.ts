import http from './http'
import type {
  ImageGeneration,
  ImageGenerationRequest,
} from '../types/imageGenerations'

/**
 * 生成说明的版本号（契约固定值）。服务端据此写一条 consent 审计；
 * 不带或版本不符会返回 422 `IMAGE_GENERATION_NOTICE_REQUIRED`。
 */
export const IMAGE_GENERATION_NOTICE_VERSION = 'image-generation-v1'

/**
 * 创建任务只等服务端**受理**（成功是 202，真正的生成是后台异步任务），所以超时不看生成耗时；
 * 但供应商受理本身也可能慢，仍给比默认 15 秒更宽的上限。
 */
const CREATE_TIMEOUT_MS = 60_000

/** 查询会**顺带推进一次**供应商状态（契约 §4.2），可能略慢于普通接口。 */
const POLL_TIMEOUT_MS = 30_000

/** 取成品：服务端要读密文、解密、重组响应，给宽松上限。 */
const CONTENT_TIMEOUT_MS = 60_000

/**
 * 图片生成接口。四个端点都在契约第 4 节冻结，前端只按契约调用：
 * 不使用公开 URL、不接触供应商任务 ID、不缓存 Base64 到本地存储。
 */
export const imageGenerationsApi = {
  async create(consultationId: string, payload: ImageGenerationRequest) {
    return (await http.post<ImageGeneration>(
      `/consultations/${consultationId}/image-generations`,
      payload,
      { timeout: CREATE_TIMEOUT_MS },
    )).data
  },
  /** 单个任务状态；轮询用。 */
  async get(id: string) {
    return (await http.get<ImageGeneration>(`/image-generations/${id}`, {
      timeout: POLL_TIMEOUT_MS,
    })).data
  },
  /** 该会话的全部任务；刷新后按 `sourceMessageId` 挂回对应回答下方。 */
  async list(consultationId: string) {
    return (await http.get<{ items: ImageGeneration[] }>(
      `/consultations/${consultationId}/image-generations`,
      { timeout: POLL_TIMEOUT_MS },
    )).data.items
  },
  /**
   * 取成品字节。鉴权接口、仅所属用户可读；服务端会带 `no-store` 与 `nosniff`。
   *
   * 到期返回 `410 GENERATED_IMAGE_EXPIRED`，未完成返回 `409 IMAGE_GENERATION_NOT_READY`。
   * 注意 `responseType: 'blob'` 下错误体也是 Blob，通用的 `sanitizeApiMessage` 读不到 `code`，
   * 所以调用方要**按 HTTP 状态判断**（与附件图片同一条经验）。
   */
  async content(id: string) {
    return (await http.get<Blob>(`/image-generations/${id}/content`, {
      responseType: 'blob',
      timeout: CONTENT_TIMEOUT_MS,
    })).data
  },
  /** 删除：已完成是永久删除，未完成只标记取消（不承诺撤销供应商费用）。 */
  async remove(id: string) {
    await http.delete(`/image-generations/${id}`)
  },
}