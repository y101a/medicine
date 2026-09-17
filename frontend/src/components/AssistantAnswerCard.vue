<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ content: string; streaming?: boolean }>()

type SectionKind = 'overview' | 'types' | 'distinctions' | 'visit' | 'summary' | 'causes' | 'followup' | 'actions' | 'warning'
interface AnswerSection { kind: SectionKind; title: string; lines: string[] }

const headings: Array<{ kind: SectionKind; title: string; aliases: string[] }> = [
  { kind: 'overview', title: '问题概览', aliases: ['问题概览', '知识概览'] },
  { kind: 'types', title: '常见类型', aliases: ['常见类型', '常见类别'] },
  { kind: 'distinctions', title: '区分要点', aliases: ['区分要点', '如何区分'] },
  { kind: 'visit', title: '何时就医', aliases: ['何时就医', '什么时候就医'] },
  { kind: 'summary', title: '情况梳理', aliases: ['情况梳理', '当前情况', '信息梳理'] },
  { kind: 'causes', title: '可能相关的常见原因', aliases: ['可能相关的常见原因', '可能原因', '常见可能原因'] },
  { kind: 'followup', title: '需要补充的信息', aliases: ['需要补充的信息', '建议补充', '建议补充的信息', '还需要了解'] },
  { kind: 'actions', title: '现在可以怎么做', aliases: ['现在可以怎么做', '日常注意', '日常建议'] },
  { kind: 'warning', title: '建议尽快就医的情况', aliases: ['建议尽快就医的情况', '就医建议', '就医提示', '紧急就医提示'] },
]

function cleanHeading(line: string) {
  return line.trim().replace(/^#{1,6}\s*/, '').replace(/^\*{1,2}|\*{1,2}$/g, '').replace(/[：:]$/, '').trim()
}

function cleanLine(line: string) {
  return line.trim()
    .replace(/^[-*•]\s*/, '')
    .replace(/^\d+[.)、]\s*/, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
}

const parsed = computed(() => {
  const intro: string[] = []
  const disclaimer: string[] = []
  const sections: AnswerSection[] = []
  let current: AnswerSection | undefined

  for (const rawLine of props.content.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    const normalized = cleanHeading(line)
    const heading = headings.find(item => item.aliases.includes(normalized))
    if (heading) {
      current = { kind: heading.kind, title: heading.title, lines: [] }
      sections.push(current)
      continue
    }
    const content = cleanLine(line)
    if (/仅供.*科普|不作确诊|不能替代医生|不替代医生/.test(content)) {
      disclaimer.push(content)
    } else if (current) {
      current.lines.push(content)
    } else {
      intro.push(content)
    }
  }

  return {
    intro,
    disclaimer: [...new Set(disclaimer)].join(' '),
    sections: sections.filter(section => section.lines.length),
    structured: sections.filter(section => section.lines.length).length >= 2,
  }
})
const isOverview = computed(() => parsed.value.sections.some(section =>
  section.kind === 'overview' || section.kind === 'types' || section.kind === 'distinctions'))
</script>

<template>
  <div v-if="!content" class="raw-answer" :class="{ streaming }">正在思考…</div>
  <article v-else-if="parsed.structured" class="answer-card" :class="{ streaming }">
    <header>
      <span class="card-mark" aria-hidden="true">✦</span>
      <div><small>{{ isOverview ? '健康知识速览' : '健康科普参考' }}</small><h3>{{ isOverview ? '先了解常见情况' : '根据您提供的信息' }}</h3></div>
    </header>
    <p v-for="line in parsed.intro" :key="line" class="card-intro">{{ line }}</p>
    <section v-for="section in parsed.sections" :key="section.kind" class="answer-section" :class="`answer-section--${section.kind}`">
      <h4><span aria-hidden="true"></span>{{ section.title }}</h4>
      <ul><li v-for="line in section.lines" :key="line">{{ line }}</li></ul>
    </section>
    <footer>{{ parsed.disclaimer || '以上仅供健康科普参考，不作确诊，不能替代医生面诊。' }}</footer>
  </article>
  <div v-else class="raw-answer" :class="{ streaming }">{{ content }}</div>
</template>

<style scoped>
.raw-answer { margin-top: 7px; white-space: pre-wrap; overflow-wrap: anywhere; color: #3d5368; }
.answer-card { width: min(690px, 100%); margin-top: 10px; overflow: hidden; border: 1px solid #dce8f2; border-radius: 16px; background: #fff; box-shadow: 0 8px 24px rgb(35 85 126 / 6%); color: #3d5368; }
.answer-card > header { display: flex; align-items: center; gap: 11px; padding: 17px 20px; border-bottom: 1px solid #e8f0f6; background: linear-gradient(135deg, #f7fbff, #fff); }
.card-mark { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px; background: #e8f4fd; color: #287dbf; font-size: 17px; }
header small { display: block; margin-bottom: 1px; color: #8194a6; font-size: 10px; letter-spacing: 1px; }
header h3 { margin: 0; color: #304b63; font-size: 16px; font-weight: 650; }
.card-intro { margin: 15px 20px 0; color: #3d5368; }
.answer-section { margin: 14px 18px; padding: 14px 16px; border-radius: 12px; background: #f7fafd; }
.answer-section h4 { display: flex; align-items: center; gap: 8px; margin: 0 0 9px; color: #3c5e79; font-size: 13px; }
.answer-section h4 span { width: 7px; height: 7px; border-radius: 50%; background: #4d94ca; box-shadow: 0 0 0 4px #e1f0fb; }
.answer-section ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.answer-section li { position: relative; padding-left: 16px; line-height: 1.75; }
.answer-section li::before { content: ''; position: absolute; top: .72em; left: 1px; width: 5px; height: 5px; border-radius: 50%; background: #91acc1; }
.answer-section--causes { border: 1px solid #e0edf7; background: #f5faff; }
.answer-section--types { border: 1px solid #e0edf7; background: #f5faff; }
.answer-section--overview { background: #f5f9fd; }
.answer-section--distinctions { border: 1px solid #dcf0e8; background: #f4fbf8; }
.answer-section--distinctions h4 { color: #34755f; }
.answer-section--distinctions h4 span, .answer-section--distinctions li::before { background: #3fa27f; }
.answer-section--visit { border: 1px solid #f1dfbc; background: #fff9ed; }
.answer-section--visit h4 { color: #a56513; }
.answer-section--visit h4 span, .answer-section--visit li::before { background: #d8922d; box-shadow: 0 0 0 4px #fae9c9; }
.answer-section--actions { border: 1px solid #dcf0e8; background: #f4fbf8; }
.answer-section--actions h4 { color: #34755f; }
.answer-section--actions h4 span, .answer-section--actions li::before { background: #3fa27f; }
.answer-section--warning { border: 1px solid #f1dfbc; background: #fff9ed; }
.answer-section--warning h4 { color: #a56513; }
.answer-section--warning h4 span, .answer-section--warning li::before { background: #d8922d; box-shadow: 0 0 0 4px #fae9c9; }
.answer-card footer { margin: 0 18px 17px; padding: 10px 12px; border-radius: 9px; background: #f2f5f7; color: #536a7d; font-size: 11px; line-height: 1.7; }
.streaming::after { content: ''; display: inline-block; width: 7px; height: 15px; margin-left: 4px; vertical-align: -2px; background: #6b98bc; animation: blink .8s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
</style>
