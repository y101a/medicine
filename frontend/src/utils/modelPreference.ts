export const MODEL_PREFERENCE_STORAGE_KEY_PREFIX = 'medical-assistant:selected-model'

function storageKey(userId: string): string {
  return `${MODEL_PREFERENCE_STORAGE_KEY_PREFIX}:${userId}`
}

export function readSelectedModelId(userId?: string | null): string {
  if (!userId) return ''
  try {
    return window.localStorage.getItem(storageKey(userId)) || ''
  } catch {
    return ''
  }
}

export function rememberSelectedModelId(userId: string | null | undefined, modelId: string): void {
  if (!userId || !modelId) return

  try {
    window.localStorage.setItem(storageKey(userId), modelId)
  } catch {
    // Storage can be unavailable in privacy-restricted browsers. The selector
    // still works for the current page and falls back to the server default.
  }
}
