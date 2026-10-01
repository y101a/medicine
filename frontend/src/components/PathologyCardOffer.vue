<script setup lang="ts">
import { Loading, Postcard } from '@element-plus/icons-vue'

defineProps<{ loading?: boolean }>()
defineEmits<{ generate: [] }>()
</script>

<template>
  <div class="pathology-card-offer">
    <span class="visually-hidden" aria-hidden="true">是否生成一张病理科普卡片</span>
    <button
      class="card-icon-button"
      type="button"
      :disabled="loading"
      aria-label="生成卡片"
      :title="loading ? '正在生成科普卡片' : '生成科普卡片'"
      @click="$emit('generate')"
    >
      <el-icon v-if="loading" class="is-loading" :size="16" aria-hidden="true"><Loading /></el-icon>
      <el-icon v-else :size="17" aria-hidden="true"><Postcard /></el-icon>
      <span class="visually-hidden">{{ loading ? '正在生成卡片' : '生成卡片' }}</span>
    </button>
  </div>
</template>

<style scoped>
.pathology-card-offer { display: inline-flex; margin-top: 10px; vertical-align: top; }
.card-icon-button { display: inline-grid; place-items: center; width: 32px; height: 32px; padding: 0;
  border: 1px solid #d7e3ee; border-radius: 9px; background: #fff; color: #4b7ea6; cursor: pointer;
  transition: border-color .15s, background .15s, color .15s; }
.card-icon-button:hover:not(:disabled) { border-color: #9cc3e0; background: #f4faff; color: #286b9d; }
.card-icon-button:focus-visible { outline: 2px solid #4b91c4; outline-offset: 2px; }
.card-icon-button:disabled { border-color: #e6ecf2; background: #f3f6f9; color: #aab9c6; cursor: default; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (prefers-reduced-motion: reduce) {
  .card-icon-button { transition: none; }
  .is-loading { animation: none; }
}
</style>
