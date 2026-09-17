import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { healthRecordsApi } from '../api/healthRecords'
import { getApiErrorMessage } from '../api/http'
import type {
  HealthRecord,
  HealthRecordCategory,
  HealthRecordSettings,
  OnboardingStatus,
} from '../types/healthRecords'

export const useHealthRecordsStore = defineStore('healthRecords', () => {
  const settings = ref<HealthRecordSettings | null>(null)
  const records = ref<HealthRecord[]>([])
  const noticeVisible = ref(false)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')

  const collectionEnabled = computed(() => settings.value?.collectionEnabled ?? true)
  const noticeChecked = ref(false)

  async function loadSettings() {
    settings.value = await healthRecordsApi.settings()
    return settings.value
  }

  async function loadRecords() {
    loading.value = true
    error.value = ''
    try {
      records.value = await healthRecordsApi.list()
    } catch (caught) {
      error.value = getApiErrorMessage(caught)
    } finally {
      loading.value = false
    }
    return records.value
  }

  /**
   * 首次登录后只提示一次：采集默认开启，之后不再打扰。
   * 这里只负责决定是否弹出通知，不写入任何记录。
   */
  async function checkFirstNotice() {
    if (noticeChecked.value) return false
    noticeChecked.value = true
    try {
      const current = await loadSettings()
      // 已看过通知、或已经关闭采集的用户都不再打扰。
      if (current.noticeSeen || !current.collectionEnabled) return false
      noticeVisible.value = true
      return true
    } catch {
      return false
    }
  }

  function closeNotice() {
    noticeVisible.value = false
  }

  /** 「跳过」只确认已读通知，保持默认采集，不写入记录。 */
  async function skipNotice() {
    saving.value = true
    try {
      settings.value = await healthRecordsApi.updateSettings({ noticeSeen: true })
      noticeVisible.value = false
    } finally {
      saving.value = false
    }
  }

  /** 「关闭采集」在首次通知里当场生效，不需要用户再去设置里找。 */
  async function disableCollection() {
    saving.value = true
    try {
      settings.value = await healthRecordsApi.updateSettings({
        noticeSeen: true,
        collectionEnabled: false,
      })
      noticeVisible.value = false
    } finally {
      saving.value = false
    }
  }

  async function submitOnboarding(status: OnboardingStatus, note?: string) {
    saving.value = true
    try {
      settings.value = await healthRecordsApi.onboarding(status, note)
      noticeVisible.value = false
      await loadRecords()
    } finally {
      saving.value = false
    }
  }

  async function setCollection(enabled: boolean) {
    saving.value = true
    try {
      settings.value = await healthRecordsApi.updateSettings({ collectionEnabled: enabled })
    } finally {
      saving.value = false
    }
    return settings.value
  }

  async function addRecord(category: HealthRecordCategory, content: string) {
    saving.value = true
    try {
      await healthRecordsApi.create({ category, content })
      await loadRecords()
    } finally {
      saving.value = false
    }
  }

  async function editRecord(id: string, content: string) {
    saving.value = true
    try {
      await healthRecordsApi.update(id, { content })
      await loadRecords()
    } finally {
      saving.value = false
    }
  }

  async function removeRecord(id: string) {
    saving.value = true
    try {
      await healthRecordsApi.remove(id)
      await loadRecords()
    } finally {
      saving.value = false
    }
  }

  function reset() {
    settings.value = null
    records.value = []
    noticeVisible.value = false
    noticeChecked.value = false
    error.value = ''
  }

  /**
   * 一次对话回答完成后触发增量更新。
   * 由后端判断是否属于医疗内容、是否已被处理过，前端只负责触发。
   */
  async function syncFromMessage(consultationId: string, messageId: string) {
    try {
      await healthRecordsApi.extract({ consultationId, messageId })
    } catch {
      // 自动更新是尽力而为，失败时静默忽略，不影响对话。
    }
  }

  return {
    settings,
    records,
    noticeVisible,
    loading,
    saving,
    error,
    collectionEnabled,
    loadSettings,
    loadRecords,
    checkFirstNotice,
    closeNotice,
    skipNotice,
    disableCollection,
    submitOnboarding,
    setCollection,
    addRecord,
    editRecord,
    removeRecord,
    syncFromMessage,
    reset,
  }
})