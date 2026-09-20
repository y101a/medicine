// 输入区的一次性引导状态。只存「是否看过」，不含任何用户文本、引用或密钥。
export const VOICE_TIP_STORAGE_KEY = 'medical-assistant:voice-input-tip-seen'

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === 'true'
  } catch {
    // 隐私模式等场景下 localStorage 不可用：当作「没看过」，只是重复提示，不影响使用。
    return false
  }
}

function writeFlag(key: string): void {
  try {
    window.localStorage.setItem(key, 'true')
  } catch {
    // 同上：写不进去也不影响本次会话内的关闭效果。
  }
}

export function readVoiceTipSeen(): boolean {
  return readFlag(VOICE_TIP_STORAGE_KEY)
}

export function rememberVoiceTipSeen(): void {
  writeFlag(VOICE_TIP_STORAGE_KEY)
}