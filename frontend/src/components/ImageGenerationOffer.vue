<script setup lang="ts">
/**
 * 回答底部的「生成科普配图」入口（方案 §7.1）。
 *
 * 只有满足条件的回答才渲染这个组件（判定在 `HomeView.canOfferGeneration`）：
 * 已完成的医疗类回答，且不是追问卡、不是失败/停止、不是紧急分流、不是普通闲聊。
 * 这里只负责「入口 + 一句费用提示」，**点击后不直接生成**——必须先经弹窗确认。
 */
defineProps<{ loading?: boolean }>()
defineEmits<{ open: [] }>()
</script>

<template>
  <div class="image-generation-offer">
    <span class="image-generation-offer__text">
      → 是否生成一张医学科普配图？<span class="image-generation-offer__hint">图片由 AI 生成，只作科普示意；每次生成可能产生费用。</span>
    </span>
    <el-button type="primary" plain size="small" :loading="loading" @click="$emit('open')">
      生成科普配图
    </el-button>
  </div>
</template>

<style scoped>
.image-generation-offer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; padding: 12px 14px; border: 1px solid #dce9f3; border-radius: 11px; background: #f7fbff; color: #48667e; font-size: 12px; }
.image-generation-offer__hint { display: block; margin-top: 4px; color: #7d8fa0; }
</style>