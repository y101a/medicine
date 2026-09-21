import { computed, ref } from 'vue'
import { attachmentsApi } from '../api/attachments'
import { getApiErrorMessage } from '../api/http'
import { ImagePrepError, prepareImageForUpload } from './imagePrep'
import type { Attachment, AttachmentKind, ImageCategory } from '../types/consultations'

/** 与后端 `schemas/consultations.py` 的 `attachment_ids` max_length 一致（2026-09-21 由 3 放宽到 5）。 */
export const ATTACHMENT_LIMIT = 5
/** 图片另有独立上限（契约：每条消息最多 3 张），图片与文档**合计**仍受 `ATTACHMENT_LIMIT` 约束。 */
export const IMAGE_LIMIT = 3
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

export function isImageAttachment(item: Attachment): boolean {
  return item.kind === 'image'
}

/**
 * 本次待发送的文档与图片。上传成功只把附件挂上来，**绝不自动发送**：
 * 解析与识别都可能出错，由用户核对后再自己点发送，和语音输入保持同一套规矩。
 */
export function useAttachments() {
  const items = ref<Attachment[]>([])
  /** 附件 id → 本地缩略图的 Object URL（只在内存里，不进 localStorage）。 */
  const previews = ref<Record<string, string>>({})
  const pendingName = ref('')
  const uploading = ref(false)
  const error = ref('')
  const count = computed(() => items.value.length)
  const imageCount = computed(() => items.value.filter(isImageAttachment).length)

  async function addFiles(files: File[], ensureConsultation: () => Promise<string>) {
    if (uploading.value || !files.length) return
    error.value = ''
    const room = ATTACHMENT_LIMIT - items.value.length
    if (room <= 0) {
      error.value = `一次最多带上 ${ATTACHMENT_LIMIT} 份附件，请先移除一份`
      return
    }
    const accepted: File[] = []
    for (const file of files.slice(0, room)) {
      if (!attachmentKindOf(file)) {
        error.value = '只支持 PDF、Word（.docx）、PPT（.pptx）、txt、md 文件；图片请用左侧的图片按钮'
        continue
      }
      if (file.size > ATTACHMENT_MAX_BYTES) {
        // 文案从常量派生，避免上限调整后提示还写着旧数字。
        error.value = `单个文档不能超过 ${ATTACHMENT_MAX_LABEL}`
        continue
      }
      accepted.push(file)
    }
    if (files.length > room) error.value = `一次最多带上 ${ATTACHMENT_LIMIT} 份附件，多余的已忽略`
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

  /**
   * 选入图片：先在本地压缩、摆正并剥掉 EXIF，再**逐张**上传（类别是每张图片自己的
   * 处理提示，混在一批里会张冠李戴）。与文档一样：传完不自动发送。
   */
  async function addImages(
    files: File[],
    imageCategory: ImageCategory,
    ensureConsultation: () => Promise<string>,
  ) {
    if (uploading.value || !files.length) return
    error.value = ''
    const imageRoom = IMAGE_LIMIT - imageCount.value
    if (imageRoom <= 0) {
      error.value = `一次最多带上 ${IMAGE_LIMIT} 张图片，请先移除一张`
      return
    }
    const room = Math.min(imageRoom, ATTACHMENT_LIMIT - items.value.length)
    if (room <= 0) {
      error.value = `图片与文档合计最多 ${ATTACHMENT_LIMIT} 项，请先移除一项`
      return
    }
    const accepted: File[] = []
    for (const file of files.slice(0, room)) {
      try {
        accepted.push(await prepareImageForUpload(file))
      } catch (cause) {
        // 本地预处理失败的消息是写给用户看的短句，直接透传。
        error.value = cause instanceof ImagePrepError
          ? cause.message
          : '图片处理失败，请换一张或改用 PDF 上传'
      }
    }
    if (files.length > room) {
      error.value = `一次最多带上 ${IMAGE_LIMIT} 张图片、与文档合计不超过 ${ATTACHMENT_LIMIT} 项，多余的已忽略`
    }
    if (!accepted.length) return

    uploading.value = true
    try {
      const consultationId = await ensureConsultation()
      for (const file of accepted) {
        pendingName.value = file.name
        const uploaded = await attachmentsApi.uploadImage(consultationId, file, imageCategory)
        items.value.push(uploaded)
        // 预览用本地这张压缩后的字节：服务端存的是加密 WebP，要另走鉴权接口取。
        if (uploaded.id) previews.value[uploaded.id] = URL.createObjectURL(file)
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
      releasePreview(attachmentId)
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
    }
  }

  function releasePreview(attachmentId: string) {
    const url = previews.value[attachmentId]
    if (!url) return
    URL.revokeObjectURL(url)
    delete previews.value[attachmentId]
  }

  /** 组件卸载或清空草稿区时必须调用，否则这些 Object URL 会一直占着内存。 */
  function releasePreviews() {
    Object.keys(previews.value).forEach(releasePreview)
  }

  function reset() {
    releasePreviews()
    items.value = []
    error.value = ''
    pendingName.value = ''
  }

  function clearError() {
    error.value = ''
  }

  return {
    items,
    previews,
    count,
    imageCount,
    pendingName,
    uploading,
    error,
    addFiles,
    addImages,
    load,
    remove,
    reset,
    clearError,
    releasePreview,
    releasePreviews,
  }
}