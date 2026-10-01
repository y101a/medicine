<script setup lang="ts">
import { computed } from 'vue'
import { CircleClose, Loading, RefreshRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
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
      class="speech-button speech-icon-button primary"
      type="button"
      :aria-label="playTitle"
      :title="playTitle"
      @click="emit('play')"
    >
      <el-icon v-if="error" :size="16" aria-hidden="true"><RefreshRight /></el-icon>
      <svg v-else class="speech-output-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 9v6h4l5 4V5L8 9H4Z" />
        <path d="M16 8.2a5 5 0 0 1 0 7.6M18.7 5.5a8.8 8.8 0 0 1 0 13" />
      </svg>
      <span class="visually-hidden">{{ playLabel }}</span>
    </button>
    <template v-else>
      <button
        v-if="state === 'loading'"
        class="speech-button speech-icon-button"
        type="button"
        disabled
        aria-label="正在生成语音"
        title="正在生成语音"
      ><el-icon class="is-loading" :size="16" aria-hidden="true"><Loading /></el-icon><span class="visually-hidden">正在生成语音</span></button>
      <button
        v-else-if="state === 'playing'"
        class="speech-button speech-icon-button"
        type="button"
        aria-label="暂停朗读"
        title="暂停朗读"
        @click="emit('pause')"
      ><el-icon :size="16" aria-hidden="true"><VideoPause /></el-icon><span class="visually-hidden">暂停</span></button>
      <button
        v-else
        class="speech-button speech-icon-button"
        type="button"
        aria-label="继续朗读"
        title="继续朗读"
        @click="emit('resume')"
      ><el-icon :size="16" aria-hidden="true"><VideoPlay /></el-icon><span class="visually-hidden">继续</span></button>
      <button
        class="speech-button speech-icon-button"
        type="button"
        aria-label="停止朗读"
        title="停止朗读"
        @click="emit('stop')"
      ><el-icon :size="16" aria-hidden="true"><CircleClose /></el-icon><span class="visually-hidden">停止</span></button>
    </template>
    <span class="speech-status" role="status" aria-live="polite">{{ statusText }}</span>
  </div>
</template>

<style scoped>
.speech-control { display: inline-flex; align-items: center; gap: 6px; margin: 10px 6px 0 0; vertical-align: top; }
.speech-icon-button { display: inline-grid; place-items: center; width: 32px; height: 32px; padding: 0;
  border: 1px solid #d7e3ee; border-radius: 9px; background: #fff; color: #4b7ea6; cursor: pointer;
  transition: border-color .15s, background .15s, color .15s; }
.speech-icon-button:hover:not(:disabled) { border-color: #9cc3e0; background: #f4faff; color: #286b9d; }
.speech-icon-button:focus-visible { outline: 2px solid #4b91c4; outline-offset: 2px; }
.speech-icon-button:disabled { border-color: #e6ecf2; background: #f3f6f9; color: #aab9c6; cursor: default; }
.speech-icon-button.primary { border-color: #cfe2f2; background: #f2f8fe; }
.speech-output-icon { width: 18px; height: 18px; fill: currentColor; }
.speech-output-icon path:last-child { fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.speech-status { color: #7b8fa1; font-size: 12px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (prefers-reduced-motion: reduce) {
  .speech-icon-button { transition: none; }
  .is-loading { animation: none; }
}
</style>
