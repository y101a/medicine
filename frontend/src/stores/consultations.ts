import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import { consultationsApi } from '../api/consultations'
import { getApiErrorMessage } from '../api/http'
import type { Consultation } from '../types/consultations'

export const useConsultationsStore = defineStore('consultations', () => {
  const auth = useAuthStore()
  const items = ref<Consultation[]>([])
  const loading = ref(false)
  const error = ref('')
  const hasMore = ref(false)
  let revision = 0
  watch(() => auth.user?.id, () => {
    revision++
    items.value = []
    loading.value = false
    error.value = ''
    hasMore.value = false
  }, { flush: 'sync' })
  async function load(more = false) {
    if (!auth.user || (more && loading.value)) return
    const token = ++revision
    const offset = more ? items.value.length : 0
    loading.value = true
    error.value = ''
    try {
      const page = await consultationsApi.list(offset)
      if (token !== revision) return
      items.value = more
        ? [...items.value, ...page.items.filter(item => !items.value.some(old => old.id === item.id))]
        : page.items
      hasMore.value = page.hasMore
    } catch (e) {
      if (token === revision) error.value = getApiErrorMessage(e)
    } finally {
      if (token === revision) loading.value = false
    }
  }
  return { items, loading, error, hasMore, load }
})
