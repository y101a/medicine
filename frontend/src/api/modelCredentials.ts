import http from './http'
import type {
  ModelCredentialSaveRequest,
  ModelCredentialSummary,
} from '../types/modelCredentials'

/**
 * 用户自带模型密钥。
 *
 * 明文只在「输入框 -> 请求体」这一条路上出现：读接口只返回掩码，前端不留存明文，
 * 也不把它放进 URL 或日志（后端同样只通过 HTTPS `Authorization` 头发给服务商）。
 */
export const modelCredentialsApi = {
  async list() {
    return (
      await http.get<{ items: ModelCredentialSummary[] }>('/users/me/model-credentials')
    ).data.items
  },

  /**
   * 保存前，后端会先用这个 Key 向对应服务商发一次 `max_tokens=1` 的最小请求验证。
   * 验证不通过（422）、服务商故障（502）、验证超时（504）、验证过频（429）都不会落库。
   * 返回的是刚保存的摘要（掩码），可直接用于就地更新列表。
   */
  async save(provider: string, apiKey: string) {
    const payload: ModelCredentialSaveRequest = { apiKey }
    return (
      await http.put<ModelCredentialSummary>(
        `/users/me/model-credentials/${provider}`,
        payload,
      )
    ).data
  },

  /** 删除后该服务商会回落到本站默认密钥（如果本站配了）。后端返回 204。 */
  async remove(provider: string) {
    await http.delete(`/users/me/model-credentials/${provider}`)
  },
}

export default modelCredentialsApi