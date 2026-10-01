import http, { ApiError, getApiErrorMessage } from './http'
import type { SpeechPresetList, SpeechRate } from '../types/speech'

/**
 * 语音输出（TTS）接口（契约 `VOICE_OUTPUT_PLAN.md` §4 冻结，前端只按契约调用）。
 *
 * 合成要等供应商出音频再由服务端转发，比默认 15 秒宽（总超时由服务端控制，这里只是不先掐断）。
 */
const SYNTHESIS_TIMEOUT_MS = 60_000

/**
 * 受控错误码 → 中文短句（契约 §4.4）。
 *
 * 注意 `responseType: 'blob'` 下**错误体也是 Blob**，统一拦截器读不到 `code`
 * （与配图、文档下载同一条经验，见 `documentGenerationsApi.content` 的注释），
 * 所以这里按 **HTTP 状态**映射。422 家族（不可朗读 / 音色不支持 / 文本过长）
 * 在浏览器侧无法区分具体码，统一给一句安全的「这条内容暂时无法朗读」；
 * 文本过长另有前端预检（见 `useSpeechOutput`），不会把超长回答送出去白等一次。
 */
const STATUS_MESSAGES: Record<number, string> = {
  404: '没有找到可朗读的回答',
  // 服务端 409 有两种含义：`SPEECH_MESSAGE_NOT_READY`（回答尚未完成）与
  // `SPEECH_MESSAGE_BUSY`（同一条回答正在生成语音，例如用户超时后重试）。
  // Blob 响应读不到 `code`，所以这里用对两种情况都成立的说法，不能只按前者写。
  409: '这条回答暂时无法朗读，请稍后再试',
  422: '这条内容暂时无法朗读',
  429: '语音生成过于频繁，请稍后再试',
  502: '语音服务暂时不可用，请稍后再试',
  503: '语音服务暂时不可用，请稍后再试',
  504: '语音生成超时，请稍后再试',
}

/** 用户主动取消（切换会话、点停止、开麦克风抢占）不算错误，调用方按这个 code 静默处理。 */
export const SPEECH_CANCELLED_CODE = 'REQUEST_CANCELLED'

export function speechErrorMessage(cause: unknown): string {
  const status = cause instanceof ApiError ? cause.status : undefined
  if (status && STATUS_MESSAGES[status]) return STATUS_MESSAGES[status]
  return getApiErrorMessage(cause)
}

export const speechApi = {
  /** 可用预设：只含产品字段。列表不可用时调用方退回 `FALLBACK_SPEECH_PRESETS`。 */
  async presets(): Promise<SpeechPresetList> {
    return (await http.get<SpeechPresetList>('/speech/presets')).data
  },
  /**
   * 合成**一条已保存的助手消息**（契约 §4.2）。
   *
   * 只传 `speechPreset` 与 `rate`：客户端**不能**提交待朗读长文本，也不能注入
   * `voice`/`instruction`/模型名——文本由服务端按 `messageId` 从数据库取。
   * 成功响应是 `audio/mpeg`，这里按 Blob 收，交给播放器做 Object URL。
   */
  async synthesize(
    consultationId: string,
    messageId: string,
    speechPreset: string,
    rate: SpeechRate,
    signal?: AbortSignal,
  ): Promise<Blob> {
    return (await http.post<Blob>(
      `/consultations/${consultationId}/messages/${messageId}/speech`,
      { speechPreset, rate },
      { responseType: 'blob', timeout: SYNTHESIS_TIMEOUT_MS, signal },
    )).data
  },
}