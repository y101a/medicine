import {
  DEFAULT_SPEECH_PRESET,
  DEFAULT_SPEECH_RATE,
  SPEECH_RATES,
  type SpeechRate,
} from '../types/speech'

/**
 * 语音输出的本机偏好：**只**保存用户选的预设与语速（契约 §6.3）。
 *
 * 三条边界：
 * 1. 不保存音频 Blob、Object URL、朗读文本或消息 id——音频是一次性临时结果。
 * 2. 不保存「语音对话模式」开关：模式只在当前页面内存里，刷新即回到关闭，
 *    避免公共电脑刷新后突然出声（契约 §6.3 的首版口径）。
 * 3. 读不到或存不进（隐私模式）一律退回默认值，不报错、不影响朗读入口可用。
 */
export const SPEECH_PRESET_STORAGE_KEY = 'medical-assistant:speech-preset'
export const SPEECH_RATE_STORAGE_KEY = 'medical-assistant:speech-rate'

export function readSpeechPreset(): string {
  try {
    return window.localStorage.getItem(SPEECH_PRESET_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function rememberSpeechPreset(presetId: string): void {
  if (!presetId) return
  try {
    window.localStorage.setItem(SPEECH_PRESET_STORAGE_KEY, presetId)
  } catch {
    // 写不进去也不影响本次会话内的选择。
  }
}

function isSpeechRate(value: number): value is SpeechRate {
  return (SPEECH_RATES as readonly number[]).includes(value)
}

export function readSpeechRate(): SpeechRate {
  try {
    const stored = Number(window.localStorage.getItem(SPEECH_RATE_STORAGE_KEY))
    return isSpeechRate(stored) ? stored : DEFAULT_SPEECH_RATE
  } catch {
    return DEFAULT_SPEECH_RATE
  }
}

export function rememberSpeechRate(rate: SpeechRate): void {
  try {
    window.localStorage.setItem(SPEECH_RATE_STORAGE_KEY, String(rate))
  } catch {
    // 同上。
  }
}

/** 存过的预设可能已下线：不在服务端白名单里就用列表默认值（谁也别猜）。 */
export function pickAvailablePreset(stored: string, available: string[], fallback: string): string {
  if (stored && available.includes(stored)) return stored
  if (fallback && available.includes(fallback)) return fallback
  return available[0] || DEFAULT_SPEECH_PRESET
}