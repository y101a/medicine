// 输入区的一次性状态：只存「是否看过/是否同意过」，不含任何用户文本、引用或密钥。
export const VOICE_TIP_STORAGE_KEY = 'medical-assistant:voice-input-tip-seen'
// 应用内录音会把音频发给语音识别服务，首次录音前要用户明确同意；同意结果只记在本机。
export const VOICE_CONSENT_STORAGE_KEY = 'medical-assistant:voice-consent-seen'
// 上传病历文档会把解析出的文字随提问交给模型；首次上传前弹一次说明，之后本机记住。
export const DOCUMENT_NOTICE_STORAGE_KEY = 'medical-assistant:document-notice-seen'
// 上传图片会把照片发给服务端固定的视觉模型识别；与文档说明分开，首次上传图片前单独确认一次。
export const IMAGE_CONSENT_STORAGE_KEY = 'medical-assistant:image-consent-seen'
/**
 * AI 科普配图的费用/标识/用途协议。与其它一次性提示不同，这里记的是**已确认的协议版本**
 * （而不是 true）：协议升版后要重新确认一次（方案第 7.1 节「确认后按协议版本记忆」）。
 */
export const IMAGE_GENERATION_NOTICE_STORAGE_KEY = 'medical-assistant:image-generation-notice-version'
/**
 * PPT/Word 科普文档生成的首次说明版本。与配图同理记「已确认的协议版本」而不是 true：
 * 说明升版要重新确认一次；**用户取消时不写这个键**（方案 §8.2「取消不记版本」）。
 */
export const DOCUMENT_GENERATION_NOTICE_STORAGE_KEY = 'medical-assistant:document-generation-notice-version'

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

export function readImageConsentSeen(): boolean {
  return readFlag(IMAGE_CONSENT_STORAGE_KEY)
}

export function rememberImageConsentSeen(): void {
  writeFlag(IMAGE_CONSENT_STORAGE_KEY)
}

/** 已确认过的配图协议版本；与当前协议版本不一致时，需要重新确认一次。 */
export function readImageGenerationNoticeVersion(): string {
  try {
    return window.localStorage.getItem(IMAGE_GENERATION_NOTICE_STORAGE_KEY) || ''
  } catch {
    // 隐私模式等场景：当作「没确认过」，只是多弹一次协议，不影响使用。
    return ''
  }
}

export function rememberImageGenerationNoticeVersion(version: string): void {
  try {
    window.localStorage.setItem(IMAGE_GENERATION_NOTICE_STORAGE_KEY, version)
  } catch {
    // 同上：写不进去也不影响本次会话内已经确认的效果。
  }
}

/** 已确认过的文档生成说明版本；与当前版本不一致时需要重新确认一次。 */
export function readDocumentGenerationNoticeVersion(): string {
  try {
    return window.localStorage.getItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY) || ''
  } catch {
    // 隐私模式等场景：当作「没确认过」，只是多弹一次说明，不影响使用。
    return ''
  }
}

export function rememberDocumentGenerationNoticeVersion(version: string): void {
  try {
    window.localStorage.setItem(DOCUMENT_GENERATION_NOTICE_STORAGE_KEY, version)
  } catch {
    // 同上：写不进去也不影响本次会话内已经确认的效果。
  }
}