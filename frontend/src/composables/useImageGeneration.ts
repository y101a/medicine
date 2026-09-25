import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { ApiError, getApiErrorMessage } from '../api/http'
import { IMAGE_GENERATION_NOTICE_VERSION, imageGenerationsApi } from '../api/imageGenerations'
import {
  IMAGE_GENERATION_ACTIVE_STATUSES,
  type ImageGeneration,
  type ImageGenerationStatus,
} from '../types/imageGenerations'

/**
 * AI 科普配图的任务状态机 + 轮询 + 成品取字节（方案 `IMAGE_GENERATION_PLAN.md` §7.1、§7.2）。
 *
 * 设计要点（都有契约依据，别照搬其它 composable 的写法）：
 * 1. **任务状态以服务端为准**。轮询失败只写一条提示，不把任务改写成 `failed`——供应商是否
 *    已经开始处理只有服务端知道，前端猜错会让用户误以为要重新付费。
 * 2. **不阻塞聊天**。轮询与应用状态都在这里，和文字回答的流式 `generating` 完全是两回事。
 * 3. **Object URL 全生命周期管理**：替换、删除、组件卸载都会 `revokeObjectURL`，否则内存里
 *    会一直挂着已经没人用的图片字节。
 */

/** 轮询退避区间（契约 §7.1 要求 2→5 秒）：刚提交时密一点，之后放慢。 */
const POLL_START_MS = 2_000
const POLL_MAX_MS = 5_000
const POLL_FACTOR = 1.5

/**
 * 受控错误码 → 中文短句（契约 §4.5）。未列出的交给统一的 `getApiErrorMessage`，
 * 它还会再过滤一次结构化文案（网关错误页、堆栈、JSON 片段都不许透传）。
 */
const ERROR_MESSAGES: Record<string, string> = {
  IMAGE_GENERATION_NOTICE_REQUIRED: '请先确认生成说明再试',
  IMAGE_GENERATION_PROMPT_INVALID: '这段描述不能用于科普配图，请改成非诊断性的科普描述',
  IMAGE_GENERATION_SOURCE_INVALID: '这条消息不能作为配图来源，请直接说「帮我生成一张关于…的图片」',
  IMAGE_GENERATION_ACTIVE: '上一张还在生成，请等它结束后再试',
  IMAGE_GENERATION_NOT_READY: '图片还在生成中，请稍候',
  IMAGE_GENERATION_RATE_LIMITED: '生成次数已达上限（10 分钟 3 次、每日 10 次），请稍后再试',
  IMAGE_GENERATION_PROVIDER_REJECTED: '这段描述没有通过内容审核，请换一种非诊断性的科普描述',
  IMAGE_GENERATION_PROVIDER_INVALID_RESPONSE: '图片服务返回异常，请稍后重试',
  IMAGE_GENERATION_PROVIDER_UNAVAILABLE: '图片生成服务暂时不可用，请稍后重试',
  IMAGE_GENERATION_PROVIDER_TIMEOUT: '图片生成超时，请稍后重试',
  IMAGE_GENERATION_NOT_CONFIGURED: '图片生成尚未配置，暂时不可用',
  GENERATED_IMAGE_EXPIRED: '这张图片已过 90 天保留期，无法再查看',
}

export function imageGenerationErrorMessage(cause: unknown): string {
  const code = cause instanceof ApiError ? cause.code : ''
  return ERROR_MESSAGES[code] || getApiErrorMessage(cause)
}

/** 用户在弹窗里确认协议后提交一次生成。 */
export interface ImageGenerationSubmitResult {
  ok: boolean
  message?: string
}

function newClientRequestId(): string {
  // 幂等键：同一用户重复提交必须复用同一个值，服务端才不会重复计费。
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `ig-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useImageGeneration(consultationId: Ref<string | null>) {
  const tasks = ref<ImageGeneration[]>([])
  /** 任务 id → 已创建的 Object URL。 */
  const objectUrls = ref<Record<string, string>>({})
  /** 任务 id → 一句短提示（轮询/取图失败、到期）。**不代表任务状态**。 */
  const notices = ref<Record<string, string>>({})
  /** 任务 id → 是否正在取成品字节。 */
  const loadingImages = ref<Record<string, boolean>>({})
  const submitting = ref(false)

  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let delay = POLL_START_MS
  let disposed = false

  /**
   * 按来源消息分组：`sourceMessageId` → 该消息下的任务（契约 §4.2 的历史恢复方式）。
   * 2026-09-25 起来源是命中意图的**用户**消息；旧数据里以回答为来源的任务仍按回答挂回。
   */
  const tasksByMessage = computed<Record<string, ImageGeneration[]>>(() => {
    const grouped: Record<string, ImageGeneration[]> = {}
    for (const task of tasks.value) {
      ;(grouped[task.sourceMessageId] ||= []).push(task)
    }
    return grouped
  })

  function replace(task: ImageGeneration) {
    const index = tasks.value.findIndex((item) => item.id === task.id)
    tasks.value = index === -1
      ? [...tasks.value, task]
      : tasks.value.map((item) => (item.id === task.id ? task : item))
  }

  function drop(id: string) {
    tasks.value = tasks.value.filter((item) => item.id !== id)
  }

  function setNotice(id: string, message: string) {
    notices.value = { ...notices.value, [id]: message }
  }

  function clearNotice(id: string) {
    if (!(id in notices.value)) return
    const next = { ...notices.value }
    delete next[id]
    notices.value = next
  }

  function releaseObjectUrl(id: string) {
    const url = objectUrls.value[id]
    if (!url) return
    URL.revokeObjectURL(url)
    const next = { ...objectUrls.value }
    delete next[id]
    objectUrls.value = next
  }

  function stopPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer)
    pollTimer = undefined
  }

  function hasActiveTask() {
    return tasks.value.some((task) => IMAGE_GENERATION_ACTIVE_STATUSES.includes(task.status))
  }

  function scheduleNextPoll() {
    if (disposed) return
    stopPolling()
    if (!hasActiveTask()) {
      delay = POLL_START_MS
      return
    }
    pollTimer = setTimeout(() => {
      void pollActiveTasks()
    }, delay)
    delay = Math.min(Math.round(delay * POLL_FACTOR), POLL_MAX_MS)
  }

  /** 取一张已生成图片的字节。到期（410）按契约把任务视为 `expired`。 */
  async function loadImage(task: ImageGeneration) {
    if (!task.imageAvailable || objectUrls.value[task.id] || loadingImages.value[task.id]) return
    loadingImages.value = { ...loadingImages.value, [task.id]: true }
    try {
      const blob = await imageGenerationsApi.content(task.id)
      releaseObjectUrl(task.id)
      objectUrls.value = { ...objectUrls.value, [task.id]: URL.createObjectURL(blob) }
      clearNotice(task.id)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 410) {
        // 内容接口的 410 与任务查询的 `expired` 是同一件事（契约 §4.3/§4.2）。
        replace({ ...task, status: 'expired', imageAvailable: false })
        setNotice(task.id, ERROR_MESSAGES.GENERATED_IMAGE_EXPIRED)
      } else {
        setNotice(task.id, imageGenerationErrorMessage(cause))
      }
    } finally {
      const next = { ...loadingImages.value }
      delete next[task.id]
      loadingImages.value = next
    }
  }

  /** 轮询一次所有未完成任务；查询会顺带推进供应商状态，所以不需要额外的「推进」接口。 */
  async function pollActiveTasks() {
    if (disposed) return
    const active = tasks.value.filter((task) =>
      IMAGE_GENERATION_ACTIVE_STATUSES.includes(task.status),
    )
    for (const task of active) {
      try {
        const updated = await imageGenerationsApi.get(task.id)
        if (disposed) return
        replace(updated)
        clearNotice(task.id)
        if (updated.status === 'completed') await loadImage(updated)
      } catch (cause) {
        // 只提示，不改任务状态：服务端才是状态的事实来源。
        setNotice(task.id, imageGenerationErrorMessage(cause))
      }
    }
    scheduleNextPoll()
  }

  /** 排序：新的在前（同一条回答下先显示最新一次生成）。 */
  function sortTasks(items: ImageGeneration[]) {
    return [...items].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  }

  /** 刷新/重新进入会话时恢复：拉该会话全部任务，并把已完成的成品取回来。 */
  async function loadHistory() {
    const id = consultationId.value
    if (!id) return
    try {
      const items = sortTasks(await imageGenerationsApi.list(id))
      if (disposed) return
      tasks.value = items
      for (const task of items) {
        if (task.status === 'completed') {
          await loadImage(task)
          continue
        }
        // 刷新后失败的旧任务只带回受控 `errorCode`（没有 prompt、没有供应商正文）：
        // 用同一张受控文案表还原一句人能读的原因，别让卡片只剩「生成失败」四个字。
        if (task.status === 'failed' && task.errorCode && ERROR_MESSAGES[task.errorCode]) {
          setNotice(task.id, ERROR_MESSAGES[task.errorCode])
        }
      }
      scheduleNextPoll()
    } catch (cause) {
      // 历史恢复失败不打断聊天：入口仍可用，用户点一次就会重新创建任务。
      console.warn('[image-generation] 恢复生成任务失败：', imageGenerationErrorMessage(cause))
    }
  }

  /**
   * 提交一次生成。每次调用都会生成**新的** `clientRequestId`：
   * 重试是用户明确点击后的一次新任务，可能产生新费用，不能当成原任务的免费重试。
   *
   * 2026-09-25 起没有提示词/风格/比例表单：主题来自**用户自己那条命中意图的消息**，
   * 服务端会重新解密取值；这里传的 `prompt` 只是契约要求的非空占位，不会被外发。
   */
  async function submit(
    sourceMessageId: string,
    prompt: string,
  ): Promise<ImageGenerationSubmitResult> {
    const id = consultationId.value
    if (!id) return { ok: false, message: '会话还没准备好，请稍后再试' }
    if (submitting.value) return { ok: false, message: '上一次提交还在处理，请稍候' }
    submitting.value = true
    try {
      const created = await imageGenerationsApi.create(id, {
        clientRequestId: newClientRequestId(),
        sourceMessageId,
        prompt: prompt.trim(),
        noticeAccepted: true,
        noticeVersion: IMAGE_GENERATION_NOTICE_VERSION,
      })
      replace(created)
      delay = POLL_START_MS
      scheduleNextPoll()
      return { ok: true }
    } catch (cause) {
      return { ok: false, message: imageGenerationErrorMessage(cause) }
    } finally {
      submitting.value = false
    }
  }

  /** 删除已完成成品或取消未完成任务（契约 §4.4）。 */
  async function remove(task: ImageGeneration) {
    try {
      await imageGenerationsApi.remove(task.id)
      releaseObjectUrl(task.id)
      clearNotice(task.id)
      const terminal: ImageGenerationStatus[] = ['completed', 'failed', 'cancelled', 'expired']
      if (terminal.includes(task.status)) drop(task.id)
      else replace({ ...task, status: 'cancelled', imageAvailable: false })
      scheduleNextPoll()
    } catch (cause) {
      setNotice(task.id, imageGenerationErrorMessage(cause))
    }
  }

  /** 重新可见时不要等满一个退避周期（页面切回来就该刷新）。 */
  function onVisibilityChange() {
    if (document.visibilityState !== 'visible') return
    delay = POLL_START_MS
    scheduleNextPoll()
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
  }

  watch(consultationId, (id, previous) => {
    if (id === previous) return
    stopPolling()
    for (const task of tasks.value) releaseObjectUrl(task.id)
    tasks.value = []
    notices.value = {}
    if (id) void loadHistory()
  })

  function dispose() {
    disposed = true
    stopPolling()
    for (const task of tasks.value) releaseObjectUrl(task.id)
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }

  onBeforeUnmount(dispose)

  return {
    tasks,
    tasksByMessage,
    submitting,
    notices,
    loadingImages,
    objectUrls,
    loadHistory,
    submit,
    remove,
    dispose,
  }
}