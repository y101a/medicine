<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { FollowUpAnswers, FollowUpCard, FollowUpQuestion } from '../types/consultations'

const props = defineProps<{ card: FollowUpCard; disabled?: boolean; answered?: boolean }>()
const emit = defineEmits<{ submit: [answers: FollowUpAnswers] }>()
const answers = reactive<FollowUpAnswers>({})

for (const question of props.card.questions) {
  if (question.type === 'multiple_choice') answers[question.id] = []
  else if (question.type === 'scale') answers[question.id] = Math.round(((question.min ?? 0) + (question.max ?? 10)) / 2)
  else answers[question.id] = ''
}

function selected(question: FollowUpQuestion, value: string) {
  const answer = answers[question.id]
  return Array.isArray(answer) ? answer.includes(value) : answer === value
}
function choose(question: FollowUpQuestion, value: string) {
  if (props.disabled || props.answered) return
  if (question.type === 'multiple_choice') {
    const values = answers[question.id] as string[]
    answers[question.id] = values.includes(value)
      ? values.filter(item => item !== value)
      : [...values, value]
  } else {
    answers[question.id] = value
  }
}
function setScale(question: FollowUpQuestion, event: Event) {
  answers[question.id] = Number((event.target as HTMLInputElement).value)
}
function setText(question: FollowUpQuestion, event: Event) {
  answers[question.id] = (event.target as HTMLInputElement).value
}
function hasAnswer(question: FollowUpQuestion) {
  const answer = answers[question.id]
  if (Array.isArray(answer)) return answer.length > 0
  return answer !== '' && answer !== undefined
}
const valid = computed(() => props.card.questions.every(question => !question.required || hasAnswer(question)))
</script>

<template>
  <article class="follow-up-card">
    <header><span aria-hidden="true">?</span><div><small>补充症状信息</small><h3>{{ card.intro }}</h3></div></header>
    <fieldset v-for="question in card.questions" :key="question.id" :disabled="disabled || answered">
      <legend>{{ question.label }}<em v-if="question.required">必填</em></legend>
      <div v-if="question.type === 'single_choice' || question.type === 'multiple_choice'" class="choices">
        <button v-for="option in question.options" :key="option.value" type="button"
          :class="{ selected: selected(question, option.value) }" @click="choose(question, option.value)">
          {{ option.label }}
        </button>
      </div>
      <div v-else-if="question.type === 'scale'" class="scale-control">
        <input type="range" :min="question.min ?? 0" :max="question.max ?? 10"
          :value="answers[question.id] as number" @input="setScale(question, $event)" />
        <strong>{{ answers[question.id] }}</strong>
      </div>
      <input v-else class="text-answer" type="text" maxlength="120" placeholder="请输入补充信息"
        :value="answers[question.id] as string" @input="setText(question, $event)" />
    </fieldset>
    <button class="submit-follow-up" type="button" :disabled="disabled || answered || !valid" @click="emit('submit', { ...answers })">
      {{ answered ? '已提交补充信息' : '提交补充信息' }}
    </button>
  </article>
</template>

<style scoped>
.follow-up-card { width: min(690px, 100%); margin-top: 10px; padding: 18px 20px 20px; border: 1px solid #dce8f2; border-radius: 16px; background: #fff; box-shadow: 0 8px 24px rgb(35 85 126 / 6%); color: #4c657a; }
header { display: flex; align-items: center; gap: 11px; margin-bottom: 18px; }
header > span { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px; background: #e8f4fd; color: #287dbf; font-size: 17px; font-weight: 700; }
header small { display: block; color: #8194a6; font-size: 10px; letter-spacing: 1px; }
h3 { margin: 2px 0 0; color: #304b63; font-size: 15px; line-height: 1.6; }
fieldset { margin: 0 0 17px; padding: 0; border: 0; }
legend { margin-bottom: 9px; color: #405b72; font-size: 13px; font-weight: 600; }
legend em { margin-left: 7px; color: #9aa8b4; font-size: 9px; font-style: normal; font-weight: 400; }
.choices { display: flex; flex-wrap: wrap; gap: 8px; }
.choices button { min-width: 78px; padding: 8px 14px; border: 1px solid #d8e3ec; border-radius: 9px; background: #fff; color: #60778b; cursor: pointer; }
.choices button:hover, .choices button.selected { border-color: #5a9bd0; background: #eef7ff; color: #2479bc; }
.scale-control { display: flex; align-items: center; gap: 14px; }
.scale-control input { flex: 1; accent-color: #347fbd; }
.scale-control strong { display: grid; place-items: center; width: 32px; height: 28px; border-radius: 8px; background: #e8f4fd; color: #287dbf; }
.text-answer { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid #d8e3ec; border-radius: 9px; outline: none; color: #496279; }
.text-answer:focus { border-color: #6aa4d2; box-shadow: 0 0 0 3px #eff7fd; }
.submit-follow-up { width: 100%; padding: 11px; border: 0; border-radius: 10px; background: #347fbd; color: #fff; cursor: pointer; }
.submit-follow-up:disabled { background: #e6edf3; color: #98a8b6; cursor: default; }
</style>
