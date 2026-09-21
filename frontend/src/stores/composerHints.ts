// 输入区的一次性状态：只存「是否看过/是否同意过」，不含任何用户文本、引用或密钥。
export const VOICE_TIP_STORAGE_KEY = 'medical-assistant:voice-input-tip-seen'
// 应用内录音会把音频发给语音识别服务，首次录音前要用户明确同意；同意结果只记在本机。
export const VOICE_CONSENT_STORAGE_KEY = 'medical-assistant:voice-consent-seen'
// 上传病历文档会把解析出的文字随提问交给模型；首次上传前弹一次说明，之后本机记住。
export const DOCUMENT_NOTICE_STORAGE_KEY = 'medical-assistant:document-notice-seen'

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

export function readVoiceConsentSeen(): boolean {
  return readFlag(VOICE_CONSENT_STORAGE_KEY)
}

export function rememberVoiceConsentSeen(): void {
  writeFlag(VOICE_CONSENT_STORAGE_KEY)
}

export function readDocumentNoticeSeen(): boolean {
  return readFlag(DOCUMENT_NOTICE_STORAGE_KEY)
}

export function rememberDocumentNoticeSeen(): void {
  writeFlag(DOCUMENT_NOTICE_STORAGE_KEY)
}