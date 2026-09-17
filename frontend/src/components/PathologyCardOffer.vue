<script setup lang="ts">
defineProps<{ loading?: boolean }>()
defineEmits<{ generate: [] }>()
</script>

<template>
  <div class="pathology-card-offer">
    <span>→ 是否生成一张病理科普卡片</span>
    <el-button type="primary" plain size="small" :loading="loading" @click="$emit('generate')">
      生成卡片
    </el-button>
  </div>
</template>

<style scoped>
.pathology-card-offer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; padding: 12px 14px; border: 1px solid #dce9f3; border-radius: 11px; background: #f7fbff; color: #48667e; font-size: 12px; }
</style>
