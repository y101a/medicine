<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { attachmentsApi } from '../api/attachments'
import { ApiError } from '../api/http'
import type { MessageAttachment } from '../types/consultations'

/**
 * 消息上的附件条。文件名与解析文字都不可信，这里只渲染**纯文本**，不碰 `v-html`，
 * 也就不存在文档内容或 OCR 结果注入 HTML 的路径。
 *
 * 图片缩略图必须现取：服务端只提供鉴权的字节接口（没有公开 URL），取到后放内存里的
 * Object URL，组件卸载时统一 revoke——不写 localStorage，也不拼 Base64 URL。
 */
const props = defineProps<{ items: MessageAttachment[]; label?: string }>()

const urls = ref<Record<string, string>>({})
const loading = ref<Record<string, boolean>>({})
const failed = ref<Record<string, boolean>>({})
const expired = ref<Record<string, boolean>>({})

function keyOf(item: MessageAttachment) {
  return item.id || ''
}

function isExpired(item: MessageAttachment) {
  return expired.value[keyOf(item)] === true || item.imageAvailable === false
}

async function loadImage(item: MessageAttachment) {
  const id = keyOf(item)
  if (!id || item.status === 'deleted' || item.imageAvailable === false) return
  if (urls.value[id] || loading.value[id] || failed.value[id] || expired.value[id]) return
  loading.value = { ...loading.value, [id]: true }
  try {
    urls.value = { ...urls.value, [id]: URL.createObjectURL(await attachmentsApi.content(id)) }
  } catch (cause) {
    // 到期是正常的保留策略结果，不是故障；`responseType: 'blob'` 下通用错误层读不到 code，
    // 所以这里按 HTTP 状态 410 判断（`IMAGE_EXPIRED`）。
    if (cause instanceof ApiError && (cause.status === 410 || cause.code === 'IMAGE_EXPIRED')) {
      expired.value = { ...expired.value, [id]: true }
    } else {
      failed.value = { ...failed.value, [id]: true }
    }
  } finally {
    const pending = { ...loading.value }
    delete pending[id]
    loading.value = pending
  }
}

watch(
  () => props.items,
  (items) => {
    items.filter(item => item.kind === 'image').forEach(item => void loadImage(item))
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  Object.values(urls.value).forEach(url => URL.revokeObjectURL(url))
  urls.value = {}
})
</script>

<template>
  <p v-if="items.length" class="attachment-line" :class="{ assistant: label }">
    <span v-if="label" class="attachment-label">{{ label }}</span>
    <template v-for="item in items" :key="item.id || `deleted-${item.displayName}`">
      <span v-if="item.kind === 'image'" class="attachment-chip image">
        <template v-if="item.status === 'deleted'">{{ item.displayName }}（已删除）</template>
        <template v-else-if="isExpired(item)">图片原件已按保留策略清理：{{ item.displayName }}</template>
        <template v-else-if="urls[keyOf(item)]">
          <img class="attachment-thumb" :src="urls[keyOf(item)]" :alt="`图片附件：${item.displayName}`" />
          <span>{{ item.displayName }}</span>
        </template>
        <template v-else-if="failed[keyOf(item)]">图片暂时无法显示：{{ item.displayName }}</template>
        <template v-else>图片加载中：{{ item.displayName }}</template>
      </span>
      <span v-else class="attachment-chip" :class="{ deleted: item.status === 'deleted' }">
        {{ item.status === 'deleted' ? `${item.displayName}（已删除）` : item.displayName }}
      </span>
    </template>
  </p>
</template>

<style scoped>
.attachment-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 8px 0 0; }
.attachment-line.assistant { margin: 0 0 10px; }
.attachment-label { color: #8798a8; font-size: 11px; }
.attachment-chip { padding: 3px 10px; border: 1px solid #d7e3ee; border-radius: 999px;
  background: #f6faff; color: #4b7ea6; font-size: 11px; line-height: 1.6; }
.attachment-chip.image { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px 3px 4px; }
.attachment-chip.deleted { border-style: dashed; border-color: #e0e6ec; background: #f7f8fa;
  color: #97a4b0; }
.attachment-thumb { width: 26px; height: 26px; border-radius: 6px; object-fit: cover;
  background: #eaf2f9; }
</style>