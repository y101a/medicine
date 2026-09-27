<script setup lang="ts">
import { computed } from 'vue'
import { formatAttachmentSize } from '../composables/useAttachments'
import {
  DOCUMENT_FORMAT_LABELS,
  DOCUMENT_GENERATION_DISCLAIMER,
  DOCUMENT_GENERATION_RETENTION_DAYS,
  DOCUMENT_GENERATION_STATUS_LABELS,
  type DocumentGeneration,
  type DocumentGenerationFile,
} from '../types/documentGenerations'

/**
 * 一份生成的科普文档的任务卡（方案 §8.1、§8.2）。
 *
 * 三条硬要求：
 * 1. 卡片必须清楚显示「AI 生成的健康科普资料」——不能伪装成医院或医生签发的文件；
 * 2. 一次任务可含 DOCX/PPTX 两个下载项，但**只有一个卡片**（方案 §8.2）；
 * 3. 下载走父组件给的鉴权字节（本组件只发事件），**不显示后端存储路径**，也**不做预览**：
 *    v1 没有服务端渲染（方案 §1.6），卡片只给文件名、大小、页数和来源数，看版式要下载后打开。
 *
 * 刻意**不放「重新生成」按钮**：方案 §8.2 要求不增加生成入口。要再来一次，用户再说一遍那句话。
 */
const props = defineProps<{
  task: DocumentGeneration
  /** 父组件汇集的短提示（轮询/下载失败、资料不足、到期），不代表任务状态。 */
  notice?: string
  /** 文件 id → 是否正在取字节。 */
  downloading?: Record<string, boolean>
}>()

const emit = defineEmits<{
  (event: 'download', file: DocumentGenerationFile): void
  (event: 'remove'): void
}>()

const statusLabel = computed(() => DOCUMENT_GENERATION_STATUS_LABELS[props.task.status])
const isPending = computed(() =>
  props.task.status === 'queued'
  || props.task.status === 'generating'
  || props.task.status === 'rendering',
)
const isCompleted = computed(() => props.task.status === 'completed')

const formatText = computed(() => props.task.formats.map((item) => DOCUMENT_FORMAT_LABELS[item]).join(' + '))

const expiresText = computed(() => {
  if (!props.task.expiresAt) return ''
  const date = new Date(props.task.expiresAt)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
})

/** 每个成品一行：格式、大小、页数（DOCX 可能拿不到页数）。 */
function fileMeta(file: DocumentGenerationFile): string {
  const parts = [formatAttachmentSize(file.byteSize)]
  if (file.pageCount && file.pageCount > 0) {
    parts.push(file.format === 'pptx' ? `${file.pageCount} 页幻灯片` : `${file.pageCount} 页`)
  }
  return parts.join(' · ')
}
</script>

<template>
  <div class="generated-document-card">
    <div class="generated-document-card__head">
      <span class="generated-document-card__status" role="status" aria-live="polite">
        {{ statusLabel }}
      </span>
      <span class="generated-document-card__meta">
        {{ formatText }}
        <template v-if="isCompleted && task.sourceCount > 0"> · 参考 {{ task.sourceCount }} 条来源</template>
        <template v-if="isCompleted && expiresText"> · 保留至 {{ expiresText }}</template>
      </span>
    </div>

    <p v-if="isCompleted && task.title" class="generated-document-card__title">{{ task.title }}</p>

    <div v-if="isPending" class="generated-document-card__pending">
      <span>正在生成，可以先继续聊天；离开页面不会取消这次生成。</span>
    </div>

    <template v-else-if="isCompleted">
      <ul v-if="task.files.length" class="generated-document-card__files">
        <li v-for="file in task.files" :key="file.id" class="generated-document-card__file">
          <span class="generated-document-card__file-name">{{ DOCUMENT_FORMAT_LABELS[file.format] }}</span>
          <span class="generated-document-card__file-meta">{{ fileMeta(file) }}</span>
          <el-button
            size="small"
            plain
            :disabled="!file.available"
            :loading="Boolean(downloading && downloading[file.id])"
            @click="emit('download', file)"
          >下载</el-button>
        </li>
      </ul>
      <p v-else class="generated-document-card__pending-text">文件暂时取不到，可以稍后刷新再试。</p>
      <p class="generated-document-card__disclaimer">{{ DOCUMENT_GENERATION_DISCLAIMER }}</p>
      <p class="generated-document-card__hint">
        本站不提供在线预览；请下载后用本机 Office / WPS 打开查看版式与排版。
      </p>
    </template>

    <p v-else-if="task.status === 'expired'" class="generated-document-card__ended">
      这份文件已过 {{ DOCUMENT_GENERATION_RETENTION_DAYS }} 天保留期，原件已按保留策略清理。
    </p>
    <p v-else class="generated-document-card__ended">
      {{ task.status === 'cancelled' ? '这次生成已取消。' : '这次生成没有成功。' }}
    </p>

    <el-alert v-if="notice" class="generated-document-card__notice" type="warning" show-icon
      :closable="false" :title="notice" />

    <div class="generated-document-card__actions">
      <el-popconfirm title="删除后无法恢复，确定删除吗？" confirm-button-text="删除" cancel-button-text="取消"
        @confirm="emit('remove')">
        <template #reference>
          <el-button size="small" text>删除</el-button>
        </template>
      </el-popconfirm>
    </div>
  </div>
</template>

<style scoped>
.generated-document-card { margin-top: 14px; padding: 12px 14px; border: 1px solid #dce9f3; border-radius: 11px; background: #fbfdff; }
.generated-document-card__head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.generated-document-card__status { color: #2f5876; font-size: 13px; font-weight: 600; }
.generated-document-card__meta { color: #7d8fa0; font-size: 12px; }
.generated-document-card__title { margin: 8px 0 0; color: #40566b; font-size: 13px; font-weight: 600; }
.generated-document-card__pending { display: flex; align-items: center; gap: 8px; margin-top: 10px; color: #6b8095; font-size: 12px; }
.generated-document-card__pending-text { margin: 10px 0 0; color: #6b8095; font-size: 12px; }
.generated-document-card__files { margin: 10px 0 0; padding: 0; list-style: none; }
.generated-document-card__file { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 0; border-top: 1px dashed #e6eef6; }
.generated-document-card__file:first-child { border-top: none; }
.generated-document-card__file-name { color: #40566b; font-size: 13px; }
.generated-document-card__file-meta { color: #7d8fa0; font-size: 12px; margin-right: auto; }
.generated-document-card__disclaimer { margin: 10px 0 0; color: #7d8fa0; font-size: 12px; line-height: 1.8; }
.generated-document-card__hint { margin: 6px 0 0; color: #8a9cab; font-size: 12px; }
.generated-document-card__ended { margin: 10px 0 0; color: #6b8095; font-size: 12px; }
.generated-document-card__notice { margin-top: 10px; }
.generated-document-card__actions { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
@media (max-width: 480px) {
  .generated-document-card__file { align-items: flex-start; }
  .generated-document-card__file-meta { width: 100%; margin-right: 0; }
}
</style>