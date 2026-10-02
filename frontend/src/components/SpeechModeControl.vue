<script setup lang="ts">
import { ref } from 'vue'
import { Headset } from '@element-plus/icons-vue'
import { SPEECH_RATE_OPTIONS, type SpeechPreset, type SpeechRate } from '../types/speech'

/**
 * 语音对话模式的**独立入口**（发送键左侧的耳机按钮）。
 *
 * 用户 2026-10-02 的两次调整：先要求把输入框里的次要入口收进一个「+」菜单，随后又要求
 * 「把语音对话模式从加号中分离」——朗读是高频动作，值得一个直接看得见的按钮，于是它回到
 * 输入框右侧动作区；「+」菜单里只剩添加附件与私人知识。
 *
 * 边界不变（契约 §6.3）：默认关闭、不落本地存储、仍需按麦克风说话、绝不持续监听。
 * 这里只做展示与事件上抛，模式开关与音色/语速的落盘都在 `HomeView.vue` / `useSpeechOutput`。
 */
defineProps<{
  speechMode: boolean
  presets: SpeechPreset[]
  preset: string
  rate: SpeechRate
  presetsNotice: string
}>()
const emit = defineEmits<{
  enable: []
  disable: []
  'update:preset': [value: string]
  'update:rate': [value: SpeechRate]
}>()

const visible = ref(false)
</script>

<template>
  <el-popover v-model:visible="visible" trigger="click" placement="top-end" :width="300"
    popper-class="speech-mode-popper">
    <template #reference>
      <button
        class="speech-mode-button"
        :class="{ active: speechMode }"
        type="button"
        :aria-pressed="speechMode"
        :title="speechMode ? '语音对话模式已开启：回答完成后自动朗读' : '语音对话模式：回答完成后自动朗读'"
        :aria-label="speechMode ? '语音对话模式已开启，点此设置音色与语速' : '开启语音对话模式并设置音色与语速'"
      ><el-icon :size="18"><Headset /></el-icon></button>
    </template>

    <div class="speech-settings-panel" role="dialog" aria-label="语音对话设置">
      <div class="speech-settings-header">
        <div>
          <strong>语音对话模式</strong>
          <small>{{ speechMode ? '已开启：回答完成后自动朗读' : '当前关闭' }}</small>
        </div>
        <button v-if="speechMode" type="button" class="speech-mode-disable" @click="emit('disable')">关闭模式</button>
        <button v-else type="button" class="speech-mode-enable" @click="emit('enable')">开启</button>
      </div>

      <template v-if="speechMode">
        <label class="speech-setting-field">
          <span>音色</span>
          <select
            class="speech-preset-select"
            aria-label="选择朗读音色"
            :value="preset"
            @change="emit('update:preset', ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="item in presets" :key="item.id" :value="item.id">{{ item.label }}</option>
          </select>
        </label>
        <label class="speech-setting-field">
          <span>语速</span>
          <select
            class="speech-rate-select"
            aria-label="选择朗读语速"
            :value="rate"
            @change="emit('update:rate', Number(($event.target as HTMLSelectElement).value) as SpeechRate)"
          >
            <option v-for="item in SPEECH_RATE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <span v-if="presetsNotice" class="speech-presets-notice" role="status">{{ presetsNotice }}</span>
      </template>

      <small class="speech-settings-note">仍需按麦克风说话，不会持续监听。</small>
    </div>
  </el-popover>
</template>

<style scoped>
.speech-mode-button { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid #d7e3ee;
  border-radius: 10px; background: #fff; color: #4b7ea6; cursor: pointer; }
.speech-mode-button:hover { border-color: #9cc3e0; background: #f4faff; }
.speech-mode-button.active { border-color: #7fb3d8; background: #e8f3fd; color: #1f6396; }
.speech-mode-button:focus-visible, .speech-mode-enable:focus-visible, .speech-mode-disable:focus-visible,
.speech-preset-select:focus-visible, .speech-rate-select:focus-visible { outline: 2px solid #4b91c4; outline-offset: 2px; }
.speech-settings-panel { display: grid; gap: 8px; }
.speech-settings-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.speech-settings-header div { display: grid; gap: 3px; }
.speech-settings-header strong { color: #315a79; font-size: 13px; }
.speech-settings-header small, .speech-settings-note { color: #8a9aaa; font-size: 11px; line-height: 1.5; }
.speech-mode-enable { padding: 4px 10px; border: 1px solid #d7e3ee; border-radius: 9px; background: #fff;
  color: #3f7ba6; font-size: 12px; cursor: pointer; }
.speech-mode-enable:hover { border-color: #9cc3e0; background: #f4faff; }
.speech-mode-disable { border: none; padding: 2px 0; background: transparent; color: #6c879c; font-size: 11px; cursor: pointer; }
.speech-mode-disable:hover { color: #286b9d; }
.speech-setting-field { display: grid; grid-template-columns: 40px minmax(0, 1fr); align-items: center; gap: 8px;
  color: #70879a; font-size: 12px; }
.speech-preset-select, .speech-rate-select { width: 100%; min-width: 0; padding: 7px 9px; border: 1px solid #d7e3ee;
  border-radius: 9px; background: #fff; color: #416681; font-size: 12px; cursor: pointer; }
.speech-presets-notice { color: #bf7a15; font-size: 11px; line-height: 1.5; }
</style>

<style>
/* 面板由 Element Plus 传送到 body，作用域选择器够不到，所以这里用 popper-class。 */
.speech-mode-popper { max-width: calc(100vw - 32px); }
</style>