/**
 * 跨重挂载的一次性语音请求（方案 `VOICE_OUTPUT_PLAN.md` §2.1、§6.3）。
 *
 * 为什么需要它：新会话的第一条消息发出后，`HomeView` 会 `router.replace` 到
 * `/app/consultations/{id}`，而工作区是 `<router-view :key="route.fullPath">`，本组件随之
 * **重新挂载**。此刻若直接在旧实例上开始播放，卸载流程会把它停掉并释放音频——用户开了
 * 「语音对话模式」却听不到第一条回答。所以这一种情况把请求排在这里，由新实例接手；
 * 队列里只放**一条**，并且只认同一个会话（不在别的会话里突然出声）。
 */
import { ref } from 'vue'

export interface PendingSpeechRequest {
  consultationId: string
  messageId: string
  text: string
  presetOverride?: string
}

/**
 * 用响应式 ref 而不是普通变量：队列与组件挂载**谁先谁后不确定**——Vue 的渲染 flush
 * 可能在 `await router.replace(...)` 期间就把新组件挂上了，那时队列还是空的。
 * 所以消费方既要「挂载时取一次」，也要能收到「挂载之后才到」的请求。
 */
export const pendingSpeech = ref<PendingSpeechRequest | null>(null)

export function rememberPendingSpeech(request: PendingSpeechRequest): void {
  pendingSpeech.value = request
}

/** 取走并清空；会话对不上时直接丢弃，不留给下一次挂载。 */
export function takePendingSpeech(consultationId: string): PendingSpeechRequest | null {
  const current = pendingSpeech.value
  if (!current || !consultationId || current.consultationId !== consultationId) {
    pendingSpeech.value = null
    return null
  }
  pendingSpeech.value = null
  return current
}

export function clearPendingSpeech(): void {
  pendingSpeech.value = null
}