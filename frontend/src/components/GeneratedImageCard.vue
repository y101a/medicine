<script setup lang="ts">
import { computed } from 'vue'
import {
  IMAGE_GENERATION_ASPECT_RATIO_LABELS,
  IMAGE_GENERATION_DISCLAIMER,
  IMAGE_GENERATION_STATUS_LABELS,
  IMAGE_GENERATION_STYLE_LABELS,
  type ImageGeneration,
} from '../types/imageGenerations'

/**
 * 一张生成图的卡片（方案 §7.1）：覆盖等待、生成中、成功、失败、过期、已删除六种状态。
 *
 * 三条硬要求：
 * 1. 成功态**必须**显示 `IMAGE_GENERATION_DISCLAIMER`——图内无标识（第九条策略）时，
 *    界面提示 + 元数据隐式标识就是这道防线，不能省。
 * 2. 「查看/下载」只用**鉴权取回的 Blob**（父组件给的 Object URL），不接触供应商 URL。
 * 3. 下载文件名固定为 `AI科普配图-YYYYMMDD.webp`，**不用用户提示词拼文件名**（避免把描述写进文件名）。
 */
const props = defineProps<{
  task: ImageGeneration
  /** 已取回成品的 Object URL；未完成或取不到时为空。 */
  url?: string
  /** 父组件汇集的短提示（轮询失败、已过期等），不代表任务状态。 */
  notice?: string
  loading?: boolean
}>()

const emit = defineEmits<{
  (event: 'retry'): void
  (event: 'remove'): void
}>()

const statusLabel = computed(() => IMAGE_GENERATION_STATUS_LABELS[props.task.status])
const isPending = computed(() => props.task.status === 'submitted' || props.task.status === 'running')
const isCompleted = computed(() => props.task.status === 'completed')
const canRetry = computed(
  () => props.task.status === 'failed'
    || props.task.status === 'expired'
    || props.task.status === 'cancelled',
)

/** 本地固定格式的文件名，不含用户输入。 */
const downloadName = computed(() => {
  const created = new Date(props.task.createdAt)
  const stamp = Number.isNaN(created.getTime())
    ? 'unknown'
    : `${created.getFullYear()}${String(created.getMonth() + 1).padStart(2, '0')}${String(created.getDate()).padStart(2, '0')}`
  return `AI科普配图-${stamp}.webp`
})

const expiresText = computed(() => {
  if (!props.task.imageExpiresAt) return ''
  const date = new Date(props.task.imageExpiresAt)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
})
</script>

<template>
  <div class="generated-image-card">
    <div class="generated-image-card__head">
      <span class="generated-image-card__status" role="status" aria-live="polite">
        {{ statusLabel }}
      </span>
      <span class="generated-image-card__meta">
        {{ IMAGE_GENERATION_STYLE_LABELS[task.style] }} · {{ IMAGE_GENERATION_ASPECT_RATIO_LABELS[task.aspectRatio] }}
        <template v-if="isCompleted && expiresText"> · 保留至 {{ expiresText }}</template>
      </span>
    </div>

    <div v-if="isPending" class="generated-image-card__pending">
      <span>正在生成，可以先继续聊天；离开页面不会取消这次生成。</span>
    </div>

    <template v-else-if="isCompleted">
      <img v-if="url" class="generated-image-card__image" :src="url" alt="AI 生成的医学科普配图" />
      <p v-else-if="loading" class="generated-image-card__pending-text">正在取回图片…</p>
      <p v-else class="generated-image-card__pending-text">图片暂时取不到，可以稍后刷新再试。</p>
      <p class="generated-image-card__disclaimer">{{ IMAGE_GENERATION_DISCLAIMER }}</p>
    </template>

    <p v-else-if="task.status === 'expired'" class="generated-image-card__ended">
      这张图片已过 90 天保留期，原件已按保留策略清理。
    </p>
    <p v-else class="generated-image-card__ended">
      {{ task.status === 'cancelled' ? '这次生成已取消。' : '这次生成没有成功。' }}
    </p>

    <el-alert v-if="notice" class="generated-image-card__notice" type="warning" show-icon
      :closable="false" :title="notice" />

    <div class="generated-image-card__actions">
      <a v-if="isCompleted && url" class="generated-image-card__download" :href="url" :download="downloadName">
        <el-button size="small" plain>下载</el-button>
      </a>
      <el-button v-if="canRetry" size="small" type="primary" plain @click="emit('retry')">
        重新生成
      </el-button>
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
.generated-image-card { margin-top: 14px; padding: 12px 14px; border: 1px solid #dce9f3; border-radius: 11px; background: #fbfdff; }
.generated-image-card__head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.generated-image-card__status { color: #2f5876; font-size: 13px; font-weight: 600; }
.generated-image-card__meta { color: #7d8fa0; font-size: 12px; }
.generated-image-card__pending { display: flex; align-items: center; gap: 8px; margin-top: 10px; color: #6b8095; font-size: 12px; }
.generated-image-card__pending-text { margin: 10px 0 0; color: #6b8095; font-size: 12px; }
.generated-image-card__image { display: block; width: 100%; max-width: 420px; margin-top: 10px; border-radius: 10px; border: 1px solid #e6eef6; background: #fff; }
.generated-image-card__disclaimer { margin: 8px 0 0; color: #7d8fa0; font-size: 12px; line-height: 1.8; }
.generated-image-card__ended { margin: 10px 0 0; color: #6b8095; font-size: 12px; }
.generated-image-card__notice { margin-top: 10px; }
.generated-image-card__actions { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.generated-image-card__download { text-decoration: none; }
</style>