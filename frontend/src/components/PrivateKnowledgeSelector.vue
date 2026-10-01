<script setup lang="ts">
import { computed } from 'vue'
import { Collection } from '@element-plus/icons-vue'
import type { PrivateKnowledgeCollection } from '../types/privateKnowledge'

const props = defineProps<{
  modelValue: string[]
  collections: PrivateKnowledgeCollection[]
  disabled?: boolean
  loading?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const countLabel = computed(() => props.modelValue.length ? `已选 ${props.modelValue.length}` : '私人知识')

function toggle(id: string, checked: boolean) {
  if (checked) {
    if (props.modelValue.length >= 3 || props.modelValue.includes(id)) return
    emit('update:modelValue', [...props.modelValue, id])
  } else {
    emit('update:modelValue', props.modelValue.filter(item => item !== id))
  }
}
</script>

<template>
  <el-popover placement="top" trigger="click" :width="300" :disabled="disabled">
    <template #reference>
      <button
        type="button"
        class="private-knowledge-trigger"
        :class="{ active: modelValue.length }"
        :disabled="disabled"
        :aria-label="`${countLabel}，打开知识库选择`"
        title="选择本次允许检索的私人知识库"
      >
        <el-icon><Collection /></el-icon><span>{{ countLabel }}</span>
      </button>
    </template>
    <section class="private-knowledge-panel" aria-label="选择私人知识库">
      <strong>本次允许检索的知识库</strong>
      <p>默认不使用。最多选择 3 个，只对本次发送的问题生效。</p>
      <span v-if="loading" class="panel-state">正在加载…</span>
      <span v-else-if="!collections.length" class="panel-state">还没有知识库，可在“我的知识库”中新建。</span>
      <label v-for="item in collections" :key="item.id" class="collection-option">
        <input
          type="checkbox"
          :checked="modelValue.includes(item.id)"
          :disabled="!modelValue.includes(item.id) && modelValue.length >= 3"
          @change="toggle(item.id, ($event.target as HTMLInputElement).checked)"
        />
        <span><b>{{ item.name }}</b><small>{{ item.documentCount }} 份文档</small></span>
      </label>
      <button v-if="modelValue.length" type="button" class="clear-selection" @click="emit('update:modelValue', [])">
        清空选择
      </button>
    </section>
  </el-popover>
</template>

<style scoped>
.private-knowledge-trigger { display: inline-flex; align-items: center; gap: 5px; height: 34px; padding: 0 9px;
  border: 1px solid #d7e3ee; border-radius: 10px; background: #fff; color: #4b7ea6; cursor: pointer; font-size: 11px; }
.private-knowledge-trigger:hover:not(:disabled), .private-knowledge-trigger.active { border-color: #86b7d9; background: #eaf5fd; color: #1f6396; }
.private-knowledge-trigger:disabled { border-color: #e6ecf2; background: #f3f6f9; color: #b3c1cd; cursor: default; }
.private-knowledge-panel strong { color: #315a79; font-size: 13px; }
.private-knowledge-panel > p { margin: 6px 0 10px; color: #8495a5; font-size: 11px; line-height: 1.6; }
.panel-state { display: block; padding: 12px 0; color: #8a9aaa; font-size: 12px; }
.collection-option { display: flex; align-items: center; gap: 9px; padding: 8px 4px; color: #48647b; cursor: pointer; }
.collection-option span { display: grid; gap: 2px; min-width: 0; }
.collection-option b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 600; }
.collection-option small { color: #96a4b1; font-size: 10px; }
.clear-selection { margin-top: 8px; padding: 0; border: 0; background: transparent; color: #4d83aa; font-size: 11px; cursor: pointer; }
</style>
