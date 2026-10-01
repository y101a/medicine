<script setup lang="ts">
import type { PrivateKnowledgeCitation } from '../types/privateKnowledge'

defineProps<{ citations: PrivateKnowledgeCitation[] }>()
</script>

<template>
  <details class="private-references">
    <summary>你的资料（{{ citations.length }}）</summary>
    <ol>
      <li v-for="item in citations" :key="item.referenceNumber">
        <template v-if="item.status === 'available'">
          <span class="reference-number">[P{{ item.referenceNumber }}]</span>
          <strong>{{ item.documentName }}</strong>
          <span>{{ item.collectionName }}<template v-if="item.locator"> · {{ item.locator }}</template></span>
        </template>
        <template v-else>
          <span class="reference-number">[P{{ item.referenceNumber }}]</span>
          <span>私人资料已删除</span>
        </template>
      </li>
    </ol>
    <p>这些是你提供的未核验资料，不等同于公共医学来源。</p>
  </details>
</template>

<style scoped>
.private-references { margin-top: 10px; padding: 10px 12px; border: 1px solid #dce9f3; border-radius: 10px; background: #f8fbfe; color: #61788c; font-size: 11px; }
summary { cursor: pointer; color: #3c6f95; font-weight: 600; }
ol { display: grid; gap: 8px; margin: 10px 0 6px; padding-left: 20px; }
li { line-height: 1.6; }
li strong { margin: 0 6px; color: #405d74; }
.reference-number { color: #2b78ad; font-weight: 600; }
p { margin: 8px 0 0; color: #8b99a7; }
</style>
