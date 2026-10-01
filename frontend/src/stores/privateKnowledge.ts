import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { privateKnowledgeApi } from '../api/privateKnowledge'
import type {
  PrivateKnowledgeCollection,
  PrivateKnowledgeDocument,
  PrivateKnowledgeSearchResult,
} from '../types/privateKnowledge'
import {
  PRIVATE_KNOWLEDGE_MAX_COLLECTIONS,
  PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS,
  PRIVATE_KNOWLEDGE_SEARCH_MAX_LIMIT,
  isPrivateKnowledgeDocumentPending,
  privateKnowledgeErrorMessage,
} from '../types/privateKnowledgeUi'

/**
 * 「我的知识库」的状态。
 *
 * 本文件是**双方内容的合并版**：上面那段（`collections` / `loading` / `error` / `load` /
 * `upsert` / `remove` / `reset`）是 Codex 为 P3 咨询接线落地时写的，**逐字保留**；
 * 下面标注 `DSH 追加` 的部分是 P1 管理页需要的文档列表、选择、轮询与增删改。
 * 管理页复用了他的 `upsert` / `remove`，没有另写一套。
 *
 * `dispose()` 只在页面卸载时叫停轮询定时器——本功能不注册任何后台任务。
 */

/** 处理中文档的轮询间隔。只问还在 `indexing` 的单个文档，不整表重拉。 */
const POLL_INTERVAL_MS = 4_000

export const usePrivateKnowledgeStore = defineStore('privateKnowledge', () => {
  // ↓↓↓ Codex 落地（P3 咨询接线依赖），逐字保留 ↓↓↓
  const collections = ref<PrivateKnowledgeCollection[]>([])
  const loading = ref(false)
  const error = ref('')

  async function load() {
    if (loading.value) return
    loading.value = true
    error.value = ''
    try {
      collections.value = await privateKnowledgeApi.collections()
    } catch (caught) {
      // 走受控错误码映射：方案 §7 要求私人知识库的错误只显示中文受控文案，
      // 不把服务端 message 透传给用户（这里原来是通用出口 `getApiErrorMessage`）。
      error.value = privateKnowledgeErrorMessage(caught)
    } finally {
      loading.value = false
    }
  }

  function upsert(item: PrivateKnowledgeCollection) {
    const index = collections.value.findIndex(existing => existing.id === item.id)
    if (index >= 0) collections.value[index] = item
    else collections.value.push(item)
  }

  function remove(id: string) {
    collections.value = collections.value.filter(item => item.id !== id)
  }

  function reset() {
    collections.value = []
    error.value = ''
    loading.value = false
  }
  // ↑↑↑ Codex 落地部分结束 ↑↑↑

  // ↓↓↓ DSH 追加：P1 管理页需要的状态 ↓↓↓
  const documents = ref<PrivateKnowledgeDocument[]>([])
  const currentCollectionId = ref('')
  const documentsLoading = ref(false)
  const documentsError = ref('')
  /** 正在改名/删除/重试的那一行，避免重复点击（同一时间只允许一个动作在飞）。 */
  const busyId = ref('')
  const polling = ref(false)

  let pollTimer: ReturnType<typeof setTimeout> | undefined

  const activeCollections = computed(
    () => collections.value.filter(item => item.status === 'active'),
  )
  const currentCollection = computed(
    () => collections.value.find(item => item.id === currentCollectionId.value) || null,
  )
  /** 上限按**可用**的库计算。 */
  const canCreateCollection = computed(
    () => activeCollections.value.length < PRIVATE_KNOWLEDGE_MAX_COLLECTIONS,
  )
  const documentSummary = computed(() => ({
    total: documents.value.length,
    ready: documents.value.filter(item => item.status === 'ready').length,
    pending: documents.value.filter(item => isPrivateKnowledgeDocumentPending(item.status)).length,
    failed: documents.value.filter(item => item.status === 'failed').length,
  }))

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = undefined
    polling.value = false
  }

  function syncCollectionCount(collectionId: string, count: number) {
    const target = collections.value.find(item => item.id === collectionId)
    if (target) target.documentCount = count
  }

  function schedulePolling() {
    stopPolling()
    if (!documents.value.some(item => isPrivateKnowledgeDocumentPending(item.status))) return
    polling.value = true
    pollTimer = setTimeout(() => { void refreshPendingDocuments() }, POLL_INTERVAL_MS)
  }

  /** 一次轮询：只问还在 `indexing` 的文档，逐个更新。 */
  async function refreshPendingDocuments() {
    const collectionId = currentCollectionId.value
    const pending = documents.value.filter(
      item => isPrivateKnowledgeDocumentPending(item.status),
    )
    if (!collectionId || !pending.length) {
      stopPolling()
      return
    }
    const results = await Promise.all(pending.map(async (item) => {
      try {
        return await privateKnowledgeApi.getDocument(item.id)
      } catch {
        // 单个文档问不到时**不改状态**：保留上一次已知状态，等下一轮再问。
        // 把「暂时问不到」写成「处理失败」会让用户白重试一次。
        return null
      }
    }))
    // 期间用户切了库：这批结果属于上一个库，丢掉。
    if (collectionId !== currentCollectionId.value) return
    for (const updated of results) {
      if (!updated) continue
      const index = documents.value.findIndex(item => item.id === updated.id)
      if (index >= 0) documents.value[index] = updated
    }
    schedulePolling()
  }

  /** 拉当前库的文档；还没选库时自动落到第一个可用库。 */
  async function loadDocuments() {
    if (!currentCollectionId.value) {
      currentCollectionId.value = activeCollections.value[0]?.id || ''
    }
    const collectionId = currentCollectionId.value
    if (!collectionId) {
      documents.value = []
      documentsError.value = ''
      return
    }
    documentsLoading.value = true
    documentsError.value = ''
    try {
      const items = await privateKnowledgeApi.documents(collectionId)
      // 响应回来时用户可能已经切库：只有仍停在同一个库时才写进界面。
      if (collectionId !== currentCollectionId.value) return
      documents.value = items
      syncCollectionCount(collectionId, items.length)
      schedulePolling()
    } catch (caught) {
      if (collectionId !== currentCollectionId.value) return
      documents.value = []
      documentsError.value = privateKnowledgeErrorMessage(caught)
    } finally {
      if (collectionId === currentCollectionId.value) documentsLoading.value = false
    }
  }

  async function selectCollection(collectionId: string) {
    if (collectionId === currentCollectionId.value) return
    stopPolling()
    currentCollectionId.value = collectionId
    documents.value = []
    documentsError.value = ''
    await loadDocuments()
  }

  async function createCollection(input: { name: string; description?: string }) {
    const created = await privateKnowledgeApi.createCollection(input.name, input.description)
    await load()
    if (created?.id) await selectCollection(created.id)
    return created
  }

  async function renameCollection(collectionId: string, input: { name: string; description?: string }) {
    busyId.value = collectionId
    try {
      const updated = await privateKnowledgeApi.updateCollection(
        collectionId,
        input.name,
        input.description,
      )
      upsert(updated)
      return updated
    } finally {
      busyId.value = ''
    }
  }

  /** 删除知识库：服务端级联删除其中全部文档与任务；列表与当前选择同时收敛。 */
  async function removeCollection(collectionId: string) {
    busyId.value = collectionId
    try {
      await privateKnowledgeApi.removeCollection(collectionId)
      remove(collectionId)
      if (currentCollectionId.value === collectionId) {
        stopPolling()
        documents.value = []
        documentsError.value = ''
        currentCollectionId.value = activeCollections.value[0]?.id || ''
        await loadDocuments()
      }
      return true
    } finally {
      busyId.value = ''
    }
  }

  /**
   * 上传一份文档。**只上传，不做本地内容解析**；扩展名与体积的预检在调用方
   * （`checkPrivateKnowledgeFile`），页数、格式真伪、内容能否解析都等服务端的受控错误码。
   */
  async function uploadDocument(file: File) {
    const collectionId = currentCollectionId.value
    if (!collectionId) return null
    const created = await privateKnowledgeApi.upload(collectionId, file)
    if (collectionId !== currentCollectionId.value) return created
    documents.value = [created, ...documents.value.filter(item => item.id !== created.id)]
    syncCollectionCount(collectionId, documents.value.length)
    schedulePolling()
    return created
  }

  async function retryDocument(documentId: string) {
    busyId.value = documentId
    try {
      const updated = await privateKnowledgeApi.retryDocument(documentId)
      const index = documents.value.findIndex(item => item.id === documentId)
      if (index >= 0) documents.value[index] = updated
      schedulePolling()
      return updated
    } finally {
      busyId.value = ''
    }
  }

  async function removeDocument(documentId: string) {
    busyId.value = documentId
    try {
      await privateKnowledgeApi.removeDocument(documentId)
      documents.value = documents.value.filter(item => item.id !== documentId)
      syncCollectionCount(currentCollectionId.value, documents.value.length)
      // 删掉最后一个处理中的文档之后要停表，否则会对空列表一直轮询。
      schedulePolling()
      return true
    } finally {
      busyId.value = ''
    }
  }

  // ↓↓↓ DSH 追加：P2 知识库内搜索（方案 §P2：只提供受控搜索接口，尚不自动送入模型） ↓↓↓
  const searchQuery = ref('')
  const searchCollectionIds = ref<string[]>([])
  const searchResults = ref<PrivateKnowledgeSearchResult[]>([])
  const searching = ref(false)
  const searchError = ref('')
  /** 是否已经搜过：用来区分「还没搜」和「搜了但没命中」两种空状态。 */
  const searchPerformed = ref(false)

  const canSearch = computed(
    () => searchQuery.value.trim().length > 0
      && searchCollectionIds.value.length > 0
      && searchCollectionIds.value.length <= PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS
      && !searching.value,
  )

  /** 设置检索范围（最多 3 个）。换范围就清掉上一轮结果，避免旧命中被当成新结果。 */
  function setSearchCollections(ids: string[]) {
    searchCollectionIds.value = ids.slice(0, PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS)
    searchResults.value = []
    searchError.value = ''
    searchPerformed.value = false
  }

  async function runSearch() {
    const query = searchQuery.value.trim()
    if (!query || !searchCollectionIds.value.length) return
    searching.value = true
    searchError.value = ''
    try {
      searchResults.value = await privateKnowledgeApi.search({
        query,
        collectionIds: [...searchCollectionIds.value],
        limit: PRIVATE_KNOWLEDGE_SEARCH_MAX_LIMIT,
      })
      searchPerformed.value = true
    } catch (caught) {
      // 搜索失败同样只显示受控中文，不透传服务端原文。
      searchResults.value = []
      searchPerformed.value = true
      searchError.value = privateKnowledgeErrorMessage(caught)
    } finally {
      searching.value = false
    }
  }

  function clearSearch() {
    searchQuery.value = ''
    searchResults.value = []
    searchError.value = ''
    searchPerformed.value = false
  }

  /** 页面卸载时调用：停掉轮询定时器（不注册任何后台任务）。 */
  function dispose() {
    stopPolling()
  }
  // ↑↑↑ DSH 追加部分结束 ↑↑↑

  return {
    collections,
    loading,
    error,
    load,
    upsert,
    remove,
    reset,
    documents,
    currentCollectionId,
    currentCollection,
    activeCollections,
    canCreateCollection,
    documentSummary,
    documentsLoading,
    documentsError,
    busyId,
    polling,
    loadDocuments,
    selectCollection,
    createCollection,
    renameCollection,
    removeCollection,
    uploadDocument,
    retryDocument,
    removeDocument,
    refreshPendingDocuments,
    searchQuery,
    searchCollectionIds,
    searchResults,
    searching,
    searchError,
    searchPerformed,
    canSearch,
    setSearchCollections,
    runSearch,
    clearSearch,
    dispose,
  }
})