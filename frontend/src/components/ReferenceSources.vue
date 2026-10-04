<script setup lang="ts">
import { Document, Link } from '@element-plus/icons-vue'
import type { MessageCitation } from '../types/consultations'

defineProps<{ citations: MessageCitation[] }>()

/** 后端对非受信网页给出的组织名形如「未核实网站（example.com）」。 */
const UNVERIFIED_PREFIX = '未核实网站（'

function isWebExcerpt(citation: MessageCitation) {
  return citation.sourceKey === 'web_search_prototype'
}

function isUnverifiedWeb(citation: MessageCitation) {
  return isWebExcerpt(citation) && citation.organization.startsWith(UNVERIFIED_PREFIX)
}

function sourceHost(citation: MessageCitation) {
  try {
    return new URL(citation.canonicalUrl).hostname
  } catch {
    return ''
  }
}

/**
 * 公开 https 网页一律可点开核对：回答已经引用了它，把链接藏起来只会让用户无法核实。
 * 安全性交给明确标注（未核实网页 / 未经医学审核），而不是靠不给链接。
 * 仍然拒绝非 https、缺主机名，以及手写原型用的 prototype.invalid 占位地址。
 */
function canOpen(citation: MessageCitation) {
  try {
    const url = new URL(citation.canonicalUrl)
    if (url.protocol !== 'https:') return false
    if (!url.hostname || url.hostname.includes('prototype.invalid')) return false
    if (isWebExcerpt(citation)) return true
    return citation.trustLevel === 'approved'
  } catch {
    return false
  }
}

function badgeText(citation: MessageCitation) {
  if (citation.trustLevel === 'approved') return '审核来源'
  if (!isWebExcerpt(citation)) return '开发原型'
  return isUnverifiedWeb(citation) ? '未核实网页' : '官网摘要'
}

function warningText(citation: MessageCitation) {
  if (!isWebExcerpt(citation)) return '该资料仅用于开发测试，未经医学专业审核。'
  return isUnverifiedWeb(citation)
    ? '网页搜索摘要，未核对原文，未经医学审核；请先核对来源网站，再决定是否采信。'
    : '网页搜索摘要，未核对原文，未经医学审核；请以官网原文为准。'
}

function linkText(citation: MessageCitation) {
  if (!isWebExcerpt(citation)) return '查看原文'
  const host = sourceHost(citation)
  return host ? `前往 ${host} 核对` : '前往来源核对'
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
              {{ badgeText(citation) }}
            </span>
          </div>
          <p>{{ citation.organization }}<template v-if="citation.sectionTitle"> · {{ citation.sectionTitle }}</template></p>
          <p v-if="isWebExcerpt(citation) && sourceHost(citation)" class="source-host">
            来源网址：<span class="source-host-name">{{ sourceHost(citation) }}</span>
          </p>
          <p v-if="citation.trustLevel === 'prototype'" class="prototype-warning">
            {{ warningText(citation) }}
          </p>
          <a v-if="canOpen(citation)" :href="citation.canonicalUrl" target="_blank" rel="noopener noreferrer nofollow">
            <el-icon aria-hidden="true"><Link /></el-icon>{{ linkText(citation) }}
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
.source-heading strong { color: #425d74; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.trust-badge { padding: 1px 6px; border-radius: 999px; font-size: 9px; line-height: 1.7; }
.trust-badge--approved { background: #e9f6f0; color: #34765e; }
.trust-badge--prototype { background: #fff3dc; color: #9a681c; }
p { margin: 3px 0 0; color: #8494a3; font-size: 10px; line-height: 1.7; overflow-wrap: anywhere; }
.prototype-warning { color: #9a753c; }
.source-host-name { color: #6b8095; }
.legacy-warning { padding: 8px 2px 2px; color: #9a753c; }
a { display: inline-flex; align-items: center; gap: 4px; margin-top: 6px; color: #367fae; font-size: 10px; text-decoration: none; overflow-wrap: anywhere; }
a:hover { text-decoration: underline; }
</style>