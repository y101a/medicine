import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { ApiError, getApiErrorMessage } from '../api/http'
import { DOCUMENT_GENERATION_NOTICE_VERSION, documentGenerationsApi } from '../api/documentGenerations'
import {
  DOCUMENT_GENERATION_ACTIVE_STATUSES,
  DOCUMENT_GENERATION_RETENTION_DAYS,
  documentDownloadName,
  type DocumentGeneration,
  type DocumentGenerationFile,
  type DocumentGenerationRequest,
  type DocumentGenerationStatus,
} from '../types/documentGenerations'

/**
 * PPT/Word 文档生成的任务状态机 + 轮询 + 鉴权下载（方案 `PPT_WORD_PLAN.md` §8.1、§9.2）。
 *
 * 与配图那套的三处关键差别，别照抄：
 * 1. **不做预览**：v1 没有服务端渲染（方案 §1.6），所以没有 Object URL 常驻，
 *    下载是「点一次 → 取字节 → 触发 → 回收」，文件字节不进内存缓存、不进本地存储。
 * 2. **幂等键按来源消息复用**：同一 `sourceMessageId` 的重复提交必须复用同一个
 *    `clientRequestId`（方案 §9.2），否则一次误点会重复调用模型、重复计费。
 * 3. **任务状态只信服务端**：轮询失败只写一条提示，不把任务改写成 `failed`。
 *
 * 卡片上**不放「重新生成」按钮**（方案 §8.2：不增加生成按钮）：失败后用户再说一次那句话即可，
 * 那会是一条新消息、新任务，不会偷偷再花一次钱。
 */

/** 轮询退避区间（方案 §8.1 要求 2→5 秒）：刚提交时密一点，之后放慢。 */
const POLL_START_MS = 2_000
const POLL_MAX_MS = 5_000
const POLL_FACTOR = 1.5

/** 下载触发的 Object URL 延后回收（毫秒），见 `download` 里的说明。 */
const REVOKE_DELAY_MS = 1_000

/**
 * 受控错误码 → 中文短句（契约 §5.5）。未列出的交给统一的 `getApiErrorMessage`，
 * 它还会再过滤一次结构化文案：内部 JSON、HTML 错误页、堆栈都不许直出。
 */
const ERROR_MESSAGES: Record<string, string> = {
  DOCUMENT_GENERATION_NOTICE_REQUIRED: '请先确认生成说明再试',
  DOCUMENT_GENERATION_REQUEST_INVALID: '请说清要 PPT 还是 Word，并给一个医学科普主题',
  DOCUMENT_GENERATION_SOURCE_INVALID: '这条消息不能作为文档来源，请直接说「帮我生成一份关于…的 PPT」',
  DOCUMENT_GENERATION_CONTENT_REJECTED: '这个要求超出科普范围（不作诊断、处方或仿造医疗文书），不能生成',
  DOCUMENT_EVIDENCE_INSUFFICIENT: '当前知识库没有足够的可引用资料，暂时无法生成这份文档',
  DOCUMENT_GENERATION_ACTIVE: '已有一个文档在生成，等它结束后再试',
  DOCUMENT_GENERATION_NOT_READY: '文件还在生成中，请稍候',
  DOCUMENT_GENERATION_RATE_LIMITED: '生成次数已达上限（10 分钟 3 次、每日 10 次），请稍后再试',
  DOCUMENT_RENDER_FAILED: '文件排版失败，请稍后重试',
  DOCUMENT_MODEL_INVALID_RESPONSE: '内容格式校验未通过，请稍后重试',
  DOCUMENT_MODEL_UNAVAILABLE: '内容生成服务暂时不可用，请稍后重试',
  DOCUMENT_GENERATION_NOT_CONFIGURED: '文档生成尚未配置，暂时不可用',
  DOCUMENT_MODEL_TIMEOUT: '内容生成超时，请稍后重试',
  GENERATED_DOCUMENT_EXPIRED: `这份文件已过 ${DOCUMENT_GENERATION_RETENTION_DAYS} 天保留期，原件已按保留策略清理`,
  // 上传 PPTX 模板的拒绝码（契约 §3.3）。文案照服务端的判定口径写，不缩小也不夸大：
  // 「结构不被支持」确实包含复杂动画、SmartArt、图表、外链、宏这些被拒的东西。
  PPT_TEMPLATE_TOO_LARGE: '模板超过 10 MiB，请换一个更小的 .pptx 文件',
  PPT_TEMPLATE_TYPE_NOT_ALLOWED: '只支持 .pptx 模板：.ppt、宏文件与加密文件都不行',
  PPT_TEMPLATE_INVALID: '这个模板打不开或结构不被支持（复杂动画、SmartArt、图表、外链等可能被拒绝）',
  PPT_TEMPLATE_NOT_APPLICABLE: '这条消息没有要求 PPT，模板套不上；想用模板请明确说「生成一份…的 PPT」',
  PPT_TEMPLATE_NOTICE_REQUIRED: '请先确认模板的保存与使用说明',
  DOCUMENT_GENERATION_TEMPLATE_CONFLICT: '这条消息已经用另一个模板生成过；换模板请重新发一条消息再试',
}

export function documentGenerationErrorMessage(cause: unknown): string {
  const code = cause instanceof ApiError ? cause.code : ''
  return ERROR_MESSAGES[code] || getApiErrorMessage(cause)
}

/** 用户在首次说明里确认后提交一次生成。 */
export interface DocumentGenerationSubmitResult {
  ok: boolean
  message?: string
}

function newClientRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `dg-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useDocumentGeneration(consultationId: Ref<string | null>) {
  const tasks = ref<DocumentGeneration[]>([])
  /** 任务 id → 一句短提示（轮询/下载失败、资料不足、到期）。**不代表任务状态**。 */
  const notices = ref<Record<string, string>>({})
  /** 文件 id → 是否正在取字节。 */
  const downloadingFiles = ref<Record<string, boolean>>({})
  const submitting = ref(false)

  /** `sourceMessageId` → 幂等键；同一条消息重复提交必须复用（方案 §9.2）。 */
  const requestIds = new Map<string, string>()

  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let delay = POLL_START_MS
  let disposed = false

  /** 按来源消息分组：`sourceMessageId` → 该消息下的任务（与配图同一套恢复方式）。 */
  const tasksByMessage = computed<Record<string, DocumentGeneration[]>>(() => {
    const grouped: Record<string, DocumentGeneration[]> = {}
    for (const task of tasks.value) {
      ;(grouped[task.sourceMessageId] ||= []).push(task)
    }
    return grouped
  })

  function replace(task: DocumentGeneration) {
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

  function setDownloading(fileId: string, value: boolean) {
    const next = { ...downloadingFiles.value }
    if (value) next[fileId] = true
    else delete next[fileId]
    downloadingFiles.value = next
  }

  function stopPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer)
    pollTimer = undefined
  }

  function hasActiveTask() {
    return tasks.value.some((task) => DOCUMENT_GENERATION_ACTIVE_STATUSES.includes(task.status))
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

  /** 轮询一次所有未完成任务。查询本身不推进 worker，只读状态。 */
  async function pollActiveTasks() {
    if (disposed) return
    const active = tasks.value.filter((task) =>
      DOCUMENT_GENERATION_ACTIVE_STATUSES.includes(task.status),
    )
    for (const task of active) {
      try {
        const updated = await documentGenerationsApi.get(task.id)
        if (disposed) return
        replace(updated)
        if (updated.status === 'failed' && updated.errorCode && ERROR_MESSAGES[updated.errorCode]) {
          setNotice(task.id, ERROR_MESSAGES[updated.errorCode])
        } else {
          clearNotice(task.id)
        }
      } catch (cause) {
        // 只提示，不改状态：服务端才是任务状态的事实来源。
        setNotice(task.id, documentGenerationErrorMessage(cause))
      }
    }
    scheduleNextPoll()
  }

  /** 排序：新的在前（同一条消息下先显示最新一次生成）。 */
  function sortTasks(items: DocumentGeneration[]) {
    return [...items].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  }

  /** 刷新 / 切换会话后恢复：拉该会话全部任务。成品不预取（没有预览），下载时再取。 */
  async function loadHistory() {
    const id = consultationId.value
    if (!id) return
    try {
      const items = sortTasks(await documentGenerationsApi.list(id))
      if (disposed) return
      tasks.value = items
      for (const task of items) {
        if (task.status === 'failed' && task.errorCode && ERROR_MESSAGES[task.errorCode]) {
          setNotice(task.id, ERROR_MESSAGES[task.errorCode])
        }
        if (task.status === 'expired') {
          setNotice(task.id, ERROR_MESSAGES.GENERATED_DOCUMENT_EXPIRED)
        }
      }
      scheduleNextPoll()
    } catch (cause) {
      // 恢复失败不打断聊天：用户再说一次那句话就能重新发起。
      console.warn('[document-generation] 恢复生成任务失败：', documentGenerationErrorMessage(cause))
    }
  }

  /**
   * 提交一次生成。主题与格式由服务端从 `sourceMessageId` 原文重新解析，前端不传任何覆盖值。
   * 同一来源消息复用 `clientRequestId`：重复提交由服务端幂等返回原任务、不会重复调用模型；
   * 同一条消息换模板则由服务端判 `DOCUMENT_GENERATION_TEMPLATE_CONFLICT`（不静默换模板）。
   *
   * `templateFile` 只在用户于确认弹窗里**主动选了 `.pptx`** 时才有值（契约 §3.3）：
   * 有值走 multipart 创建接口，没值仍是原 JSON 接口，行为与之前完全一致。
   */
  async function submit(
    sourceMessageId: string,
    templateFile: File | null = null,
  ): Promise<DocumentGenerationSubmitResult> {
    const id = consultationId.value
    if (!id) return { ok: false, message: '会话还没准备好，请稍后再试' }
    if (submitting.value) return { ok: false, message: '上一次提交还在处理，请稍候' }
    const existing = requestIds.get(sourceMessageId)
    const clientRequestId = existing || newClientRequestId()
    requestIds.set(sourceMessageId, clientRequestId)
    submitting.value = true
    try {
      const payload: DocumentGenerationRequest = {
        clientRequestId,
        sourceMessageId,
        noticeAccepted: true,
        noticeVersion: DOCUMENT_GENERATION_NOTICE_VERSION,
      }
      const created = templateFile
        ? await documentGenerationsApi.createWithTemplate(id, payload, templateFile)
        : await documentGenerationsApi.create(id, payload)
      replace(created)
      delay = POLL_START_MS
      scheduleNextPoll()
      return { ok: true }
    } catch (cause) {
      return { ok: false, message: documentGenerationErrorMessage(cause) }
    } finally {
      submitting.value = false
    }
  }

  /**
   * 鉴权取字节并触发下载。文件名由前端按固定格式生成，**不含用户主题**
   * （服务端 `Content-Disposition` 用同一套命名，两边一致）。
   */
  async function download(task: DocumentGeneration, file: DocumentGenerationFile) {
    if (!file.available || downloadingFiles.value[file.id]) return
    setDownloading(file.id, true)
    try {
      const blob = await documentGenerationsApi.content(task.id, file.id)
      if (disposed) return
      const url = URL.createObjectURL(blob)
      try {
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = documentDownloadName(file.format, task.createdAt)
        anchor.rel = 'noopener'
        document.body.appendChild(anchor)
        anchor.click()
        anchor.remove()
      } finally {
        // 方案 §8.2 要求「触发后及时回收」，但**不在同一帧同步 revoke**：
        // 按既有经验延后一拍，避免浏览器还没开始读 Blob 就失效（本项目未实测同步 revoke 的后果）。
        setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)
      }
      clearNotice(task.id)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 410) {
        // 内容接口的 410 与任务查询的 `expired` 是同一件事（契约 §5.3）。
        replace({ ...task, status: 'expired', files: [] })
        setNotice(task.id, ERROR_MESSAGES.GENERATED_DOCUMENT_EXPIRED)
      } else {
        setNotice(task.id, documentGenerationErrorMessage(cause))
      }
    } finally {
      setDownloading(file.id, false)
    }
  }

  /** 删除已完成成品或取消未完成任务（契约 §5.4）。 */
  async function remove(task: DocumentGeneration) {
    try {
      await documentGenerationsApi.remove(task.id)
      clearNotice(task.id)
      const terminal: DocumentGenerationStatus[] = ['completed', 'failed', 'cancelled', 'expired']
      if (terminal.includes(task.status)) drop(task.id)
      else replace({ ...task, status: 'cancelled', files: [] })
      scheduleNextPoll()
    } catch (cause) {
      setNotice(task.id, documentGenerationErrorMessage(cause))
    }
  }

  /** 页面重新可见时不必等满一个退避周期。 */
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
    tasks.value = []
    notices.value = {}
    downloadingFiles.value = {}
    if (id) void loadHistory()
  })

  function dispose() {
    disposed = true
    stopPolling()
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
    downloadingFiles,
    loadHistory,
    submit,
    download,
    remove,
    dispose,
  }
}