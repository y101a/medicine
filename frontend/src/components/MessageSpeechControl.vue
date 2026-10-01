<script setup lang="ts">
import { computed } from 'vue'
import type { SpeechPlaybackState } from '../types/speech'

/**
 * 单条助手回答的语音输出控件（方案 `VOICE_OUTPUT_PLAN.md` §6.2）。
 *
 * 只负责「这条消息该怎么显示、点了发什么事件」，播放器状态与音频生命周期都在
 * `useSpeechOutput`（整页单播放器）里；这样同一时间只有一段音频，第二条消息开始播放
 * 时旧的会被抢占。
 *
 * 可访问性：状态用 `role="status"` + `aria-live="polite"` 播报，但**不**连续播报播放秒数；
 * 动效尊重 `prefers-reduced-motion`。
 */
const props = defineProps<{
  state: SpeechPlaybackState
  /** 受控中文短句；只有当前消息的错误会传进来。 */
  error?: string
  /** 当前预设展示名，只用于提示这条会用什么音色朗读。 */
  presetLabel?: string
}>()

const emit = defineEmits<{
  (event: 'play'): void
  (event: 'pause'): void
  (event: 'resume'): void
  (event: 'stop'): void
}>()

const statusText = computed(() => {
  if (props.error) return props.error
  if (props.state === 'loading') return '正在生成语音…'
  if (props.state === 'playing') return '正在朗读'
  if (props.state === 'paused') return '已暂停'
  if (props.state === 'ready') return '语音已生成，点击播放'
  return ''
})

const playLabel = computed(() => {
  if (props.error) return '重试'
  if (props.state === 'ready') return '点击播放'
  return '朗读'
})

const playTitle = computed(() => (props.presetLabel
  ? `${playLabel.value}（${props.presetLabel}）`
  : playLabel.value))
</script>

<template>
  <div class="speech-control">
    <button
      v-if="state === 'idle' || state === 'ready'"
      class="speech-button primary"
      type="button"
      :aria-label="playTitle"
      :title="playTitle"
      @click="emit('play')"
    >{{ playLabel }}</button>
    <template v-else>
      <button
        v-if="state === 'loading'"
        class="speech-button"
        type="button"
        disabled
        aria-label="正在生成语音"
        title="正在生成语音"
      >正在生成语音…</button>
      <button
        v-else-if="state === 'playing'"
        class="speech-button"
        type="button"
        aria-label="暂停朗读"
        title="暂停朗读"
        @click="emit('pause')"
      >暂停</button>
      <button
        v-else
        class="speech-button"
        type="button"
        aria-label="继续朗读"
        title="继续朗读"
        @click="emit('resume')"
      >继续</button>
      <button
        class="speech-button"
        type="button"
        aria-label="停止朗读"
        title="停止朗读"
        @click="emit('stop')"
      >停止</button>
    </template>
    <span class="speech-status" role="status" aria-live="polite">{{ statusText }}</span>
  </div>
</template>

<style scoped>
.speech-control { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.speech-button { padding: 4px 11px; border: 1px solid #d7e3ee; border-radius: 9px; background: #fff;
  color: #4b7ea6; font-size: 12px; cursor: pointer; transition: border-color .15s, background .15s; }
.speech-button:hover:not(:disabled) { border-color: #9cc3e0; background: #f4faff; }
.speech-button:disabled { border-color: #e6ecf2; background: #f3f6f9; color: #b3c1cd; cursor: default; }
.speech-button.primary { border-color: #cfe2f2; background: #f2f8fe; }
.speech-status { color: #7b8fa1; font-size: 12px; }
@media (prefers-reduced-motion: reduce) {
  .speech-button { transition: none; }
}
</style>