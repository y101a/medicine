<script setup lang="ts">
import { Document, Link } from '@element-plus/icons-vue'
import type { MessageCitation } from '../types/consultations'

defineProps<{ citations: MessageCitation[] }>()

function canOpen(citation: MessageCitation) {
  try {
    const url = new URL(citation.canonicalUrl)
    if (url.protocol !== 'https:') return false
    if (citation.trustLevel === 'approved') return !url.hostname.includes('prototype.invalid')
    if (citation.sourceKey !== 'web_search_prototype') return false
    return ['nhc.gov.cn', 'chinacdc.cn', 'nmpa.gov.cn']
      .some((domain) => url.hostname === domain || url.hostname.endsWith(`.${domain}`))
  } catch {
    return false
  }
}
</script>

<template>
  <details v-if="citations.length" class="reference-sources">
    <summary>
      <span class="summary-main">
        <el-icon aria-hidden="true"><Document /></el-icon>
        {{ citations.some(item => item.referenceNumber == null) ? '历史检索资料（引用未核验）' : '参考资料' }} {{ citations.length }} 条
      </span>
      <span class="summary-hint">展开查看</span>
    </summary>
    <div class="source-list">
      <p v-if="citations.some(item => item.referenceNumber == null)" class="legacy-warning">
        旧版消息只保存了检索候选资料，无法确认回答是否引用了这些内容；请勿视为回答依据。
      </p>
      <article v-for="(citation, index) in citations" :key="`${citation.canonicalUrl}:${citation.referenceNumber ?? index}`" class="source-item">
        <div class="source-number" :aria-label="`来源${citation.referenceNumber ?? index + 1}`">{{ citation.referenceNumber ?? index + 1 }}</div>
        <div class="source-content">
          <div class="source-heading">
            <strong>{{ citation.title }}</strong>
            <span :class="['trust-badge', `trust-badge--${citation.trustLevel}`]">
              {{ citation.trustLevel === 'approved' ? '审核来源' : citation.sourceKey === 'web_search_prototype' ? '联网原型' : '开发原型' }}
            </span>
          </div>
          <p>{{ citation.organization }}<template v-if="citation.sectionTitle"> · {{ citation.sectionTitle }}</template></p>
          <p v-if="citation.trustLevel === 'prototype'" class="prototype-warning">
            {{ citation.sourceKey === 'web_search_prototype'
              ? '联网搜索摘要，仅用于开发测试；未核对原文，未经医学专业审核。'
              : '该资料仅用于开发测试，未经医学专业审核。' }}
          </p>
          <a v-if="canOpen(citation)" :href="citation.canonicalUrl" target="_blank" rel="noopener noreferrer">
            <el-icon aria-hidden="true"><Link /></el-icon>{{ citation.sourceKey === 'web_search_prototype' ? '前往官网核对' : '查看原文' }}
          </a>
        </div>
      </article>
    </div>
  </details>
</template>

<style scoped>
.reference-sources { width: min(690px, 100%); margin-top: 13px; border: 1px solid #dfe9f1; border-radius: 12px; background: #fbfdff; color: #60758a; }
summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 13px; cursor: pointer; list-style: none; user-select: none; }
summary::-webkit-details-marker { display: none; }
.summary-main { display: flex; align-items: center; gap: 7px; color: #53738e; font-size: 12px; font-weight: 600; }
.summary-main .el-icon { color: #4388bc; }
.summary-hint { color: #98a7b4; font-size: 10px; }
details[open] .summary-hint { font-size: 0; }
details[open] .summary-hint::after { content: '收起'; font-size: 10px; }
.source-list { display: grid; gap: 0; padding: 0 13px 9px; border-top: 1px solid #edf2f6; }
.source-item { display: flex; gap: 10px; padding: 12px 2px; }
.source-item + .source-item { border-top: 1px solid #edf2f6; }
.source-number { display: grid; place-items: center; width: 22px; height: 22px; flex: 0 0 22px; border-radius: 7px; background: #eaf4fb; color: #377fae; font-size: 10px; font-weight: 700; }
.source-content { min-width: 0; flex: 1; }
.source-heading { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 7px; }
.source-heading strong { color: #425d74; font-size: 12px; line-height: 1.6; }
.trust-badge { padding: 1px 6px; border-radius: 999px; font-size: 9px; line-height: 1.7; }
.trust-badge--approved { background: #e9f6f0; color: #34765e; }
.trust-badge--prototype { background: #fff3dc; color: #9a681c; }
p { margin: 3px 0 0; color: #8494a3; font-size: 10px; line-height: 1.7; }
.prototype-warning { color: #9a753c; }
.legacy-warning { padding: 8px 2px 2px; color: #9a753c; }
a { display: inline-flex; align-items: center; gap: 4px; margin-top: 6px; color: #367fae; font-size: 10px; text-decoration: none; }
a:hover { text-decoration: underline; }
</style>
