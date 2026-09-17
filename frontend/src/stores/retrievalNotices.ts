// One transient status per consultation. No patient text, citations, or API keys.
const notices = new Map<string, string>()

function key(userId: string | undefined, consultationId: string) {
  return userId && consultationId ? `${userId}:${consultationId}` : ''
}

export function readRetrievalNotice(userId: string | undefined, consultationId: string) {
  return notices.get(key(userId, consultationId)) || ''
}

export function rememberRetrievalNotice(userId: string | undefined, consultationId: string, notice: string) {
  const entry = key(userId, consultationId)
  if (!entry) return
  if (notice) notices.set(entry, notice)
  else notices.delete(entry)
}
