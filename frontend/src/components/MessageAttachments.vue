<script setup lang="ts">
import type { MessageAttachment } from '../types/consultations'

/**
 * 消息上的附件条。只渲染**纯文本**文件名：文件名与解析文字都不可信，
 * 这里不碰 `v-html`，也就不存在文档内容注入 HTML 的路径。
 */
defineProps<{ items: MessageAttachment[]; label?: string }>()
</script>

<template>
  <p v-if="items.length" class="attachment-line" :class="{ assistant: label }">
    <span v-if="label" class="attachment-label">{{ label }}</span>
    <span
      v-for="item in items"
      :key="item.id || `deleted-${item.displayName}`"
      class="attachment-chip"
      :class="{ deleted: item.status === 'deleted' }"
    >
      {{ item.status === 'deleted' ? `${item.displayName}（已删除）` : item.displayName }}
    </span>
  </p>
</template>

<style scoped>
.attachment-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 8px 0 0; }
.attachment-line.assistant { margin: 0 0 10px; }
.attachment-label { color: #8798a8; font-size: 11px; }
.attachment-chip { padding: 3px 10px; border: 1px solid #d7e3ee; border-radius: 999px;
  background: #f6faff; color: #4b7ea6; font-size: 11px; line-height: 1.6; }
.attachment-chip.deleted { border-style: dashed; border-color: #e0e6ec; background: #f7f8fa;
  color: #97a4b0; }
</style>