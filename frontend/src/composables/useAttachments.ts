import { computed, ref } from 'vue'
import { attachmentsApi } from '../api/attachments'
import { getApiErrorMessage } from '../api/http'
import type { Attachment, AttachmentKind } from '../types/consultations'

/** 与后端 `schemas/consultations.py` 的 `attachment_ids` max_length 一致（2026-09-21 由 3 放宽到 5）。 */
export const ATTACHMENT_LIMIT = 5
/** 与后端 `attachment_max_bytes` 一致（2026-09-21 由 10 MB 放宽到 30 MB）；真正判定仍以服务端为准。 */
export const ATTACHMENT_MAX_BYTES = 30 * 1024 * 1024
const ATTACHMENT_MAX_MB = ATTACHMENT_MAX_BYTES / (1024 * 1024)
const ATTACHMENT_MAX_LABEL = `${Number.isInteger(ATTACHMENT_MAX_MB) ? ATTACHMENT_MAX_MB : ATTACHMENT_MAX_MB.toFixed(1)} MB`

const KIND_BY_EXTENSION: Record<string, AttachmentKind> = {
  pdf: 'pdf',
  docx: 'docx',
  pptx: 'pptx',
  txt: 'txt',
  md: 'md',
}

/**
 * 只做「明显不合规」的本地拦截（扩展名、体积、数量），让用户立刻看到问题；
 * 文档是否真能解析、是否扫描件、是否加密，都由服务端解析结果决定。
 */
export function attachmentKindOf(file: File): AttachmentKind | null {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  return KIND_BY_EXTENSION[extension] ?? null
}

export function formatAttachmentSize(byteSize: number): string {
  if (byteSize >= 1024 * 1024) return `${(byteSize / (1024 * 1024)).toFixed(1)} MB`
  return `${Math.max(1, Math.round(byteSize / 1024))} KB`
}

/**
 * 本次待发送的文档。上传成功只把文档挂上来，**绝不自动发送**：文档解析可能出错，
 * 由用户核对后再自己点发送，和语音输入保持同一套规矩。
 */
export function useAttachments() {
  const items = ref<Attachment[]>([])
  const pendingName = ref('')
  const uploading = ref(false)
  const error = ref('')
  const count = computed(() => items.value.length)

  async function addFiles(files: File[], ensureConsultation: () => Promise<string>) {
    if (uploading.value || !files.length) return
    error.value = ''
    const room = ATTACHMENT_LIMIT - items.value.length
    if (room <= 0) {
      error.value = `一次最多带上 ${ATTACHMENT_LIMIT} 份文档，请先移除一份`
      return
    }
    const accepted: File[] = []
    for (const file of files.slice(0, room)) {
      if (!attachmentKindOf(file)) {
        error.value = '只支持 PDF、Word（.docx）、PPT（.pptx）、txt、md 文件'
        continue
      }
      if (file.size > ATTACHMENT_MAX_BYTES) {
        // 文案从常量派生，避免上限调整后提示还写着旧数字。
        error.value = `单个文档不能超过 ${ATTACHMENT_MAX_LABEL}`
        continue
      }
      accepted.push(file)
    }
    if (files.length > room) error.value = `一次最多带上 ${ATTACHMENT_LIMIT} 份文档，多余的已忽略`
    if (!accepted.length) return

    uploading.value = true
    try {
      const consultationId = await ensureConsultation()
      for (const file of accepted) {
        pendingName.value = file.name
        items.value.push(await attachmentsApi.upload(consultationId, file))
      }
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
    } finally {
      pendingName.value = ''
      uploading.value = false
    }
  }

  async function load(consultationId: string) {
    try {
      items.value = await attachmentsApi.list(consultationId)
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
    }
  }

  async function remove(attachmentId: string) {
    error.value = ''
    try {
      await attachmentsApi.remove(attachmentId)
      items.value = items.value.filter(item => item.id !== attachmentId)
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
    }
  }

  function reset() {
    items.value = []
    error.value = ''
    pendingName.value = ''
  }

  function clearError() {
    error.value = ''
  }

  return { items, count, pendingName, uploading, error, addFiles, load, remove, reset, clearError }
}