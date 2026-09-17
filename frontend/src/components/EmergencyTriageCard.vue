<script setup lang="ts">
import type { TriageResult } from '../types/consultations'

defineProps<{ triage: TriageResult }>()
</script>

<template>
  <article class="emergency-card" role="alert" aria-live="assertive">
    <header><span aria-hidden="true">!</span><div><small>红旗症状预检</small><h3>{{ triage.title }}</h3></div></header>
    <p class="summary">{{ triage.summary }}</p>
    <section><h4>检测到的危险信号</h4><ul><li v-for="reason in triage.reasons" :key="reason">{{ reason }}</li></ul></section>
    <section class="actions"><h4>请立即采取行动</h4><ol><li v-for="action in triage.actions" :key="action">{{ action }}</li></ol></section>
    <a class="call-link" href="tel:120">拨打 120</a>
    <footer>
      这是基于文字规则的安全预检，可能误判或漏判。如您认为情况危急，请不要等待系统判断，立即拨打 120。
      <span v-if="triage.ruleVersion">规则版本 {{ triage.ruleVersion }}</span>
    </footer>
  </article>
</template>

<style scoped>
.emergency-card { max-width: 690px; margin: 14px 0 0 auto; padding: 19px 21px; border: 1px solid #efc7bd; border-radius: 16px; background: #fff9f7; box-shadow: 0 8px 24px rgb(145 53 32 / 8%); color: #664d48; }
header { display: flex; align-items: center; gap: 11px; }
header > span { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: #c84b35; color: #fff; font-size: 20px; font-weight: 800; }
header small { color: #a56e63; font-size: 10px; letter-spacing: 1px; }
h3 { margin: 2px 0 0; color: #8f2f20; font-size: 18px; }
.summary { margin: 15px 0; line-height: 1.8; }
section { margin: 12px 0; padding: 13px 15px; border-radius: 11px; background: #fff; }
h4 { margin: 0 0 8px; color: #7c4035; font-size: 13px; }
ul, ol { display: grid; gap: 7px; margin: 0; padding-left: 20px; line-height: 1.7; }
.actions { border: 1px solid #f1d4cc; }
.call-link { display: block; margin: 14px 0; padding: 11px; border-radius: 10px; background: #ba3e2a; color: #fff; text-align: center; text-decoration: none; font-weight: 650; }
footer { color: #8f716b; font-size: 11px; line-height: 1.7; }
footer span { display: block; margin-top: 4px; color: #a48781; }
</style>
