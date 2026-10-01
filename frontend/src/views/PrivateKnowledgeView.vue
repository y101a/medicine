<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePrivateKnowledgeStore } from '../stores/privateKnowledge'
import {
  readPrivateKnowledgeNoticeVersion,
  rememberPrivateKnowledgeNoticeVersion,
} from '../stores/composerHints'
import { formatAttachmentSize } from '../composables/useAttachments'
import PrivateKnowledgeNoticeDialog from '../components/PrivateKnowledgeNoticeDialog.vue'
import type {
  PrivateKnowledgeCollection,
  PrivateKnowledgeDocument,
} from '../types/privateKnowledge'
import {
  PRIVATE_KNOWLEDGE_ACCEPT,
  PRIVATE_KNOWLEDGE_BOUNDARY_HINT,
  PRIVATE_KNOWLEDGE_DOCUMENT_STATUS_LABELS,
  PRIVATE_KNOWLEDGE_ERROR_MESSAGES,
  PRIVATE_KNOWLEDGE_MAX_BYTES,
  PRIVATE_KNOWLEDGE_MAX_COLLECTIONS,
  PRIVATE_KNOWLEDGE_NOTICE_SHORT,
  PRIVATE_KNOWLEDGE_NOTICE_VERSION,
  PRIVATE_KNOWLEDGE_SCOPE_HINT,
  PRIVATE_KNOWLEDGE_SEARCH_EMPTY,
  PRIVATE_KNOWLEDGE_SEARCH_HINT,
  PRIVATE_KNOWLEDGE_SEARCH_LIMIT_HINT,
  PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS,
  PRIVATE_KNOWLEDGE_SEARCH_MAX_QUERY_LENGTH,
  PRIVATE_KNOWLEDGE_SEARCH_SCOPE_REQUIRED,
  checkPrivateKnowledgeFile,
  privateKnowledgeErrorMessage,
  privateKnowledgeKindLabel,
  privateKnowledgeSimilarityLabel,
} from '../types/privateKnowledgeUi'

/**
 * 「我的知识库」管理页（方案 §8.1、§9、§P2）。
 *
 * P1：知识库列表与新建/改名/删除、上传（首次一次性说明）、文档状态与失败原因、重试与删除。
 * P2：知识库内搜索（`POST /private-knowledge/search`）——只做检索，**不把命中送进对话**。
 *
 * 与 Codex 的 P3 咨询接线严格分开：本页不 import 他的选择器/引用组件，搜索范围用页面内的
 * 普通复选框（最多 3 个）。数据层类型在 `types/privateKnowledge.ts`（他的文件，我只追加不改）。
 */
const store = usePrivateKnowledgeStore()
const fileInput = ref<HTMLInputElement | null>(null)
const noticeVisible = ref(false)
const pendingFile = ref<File | null>(null)
const uploading = ref(false)
const uploadError = ref('')

const maxSizeText = computed(() => formatAttachmentSize(PRIVATE_KNOWLEDGE_MAX_BYTES))
const collectionsAtLimit = computed(() => !store.canCreateCollection)

onMounted(async () => {
  await store.load()
  // 库列表到位后再拉当前库的文档（store.loadDocuments 会在未选库时落到第一个可用库）。
  await store.loadDocuments()
  // P2 搜索范围默认落在当前库；用户可在搜索区改成 1–3 个，换库不重置。
  if (store.currentCollectionId) store.setSearchCollections([store.currentCollectionId])
})
// 离开页面就停掉轮询定时器（本功能不注册任何后台任务）。
onBeforeUnmount(() => store.dispose())

function reload() {
  void store.load().then(() => store.loadDocuments())
}

// ---- P2：知识库内搜索 ----
// 范围用页面内的普通复选框（最多 3 个），不复用咨询页的选择器组件（那是 P3 的文件）。

/** 勾选/取消一个知识库；已到 3 个上限时不再加。换范围会清掉上一轮结果（store 里做）。 */
function toggleSearchScope(collectionId: string, checked: boolean) {
  const current = store.searchCollectionIds
  if (checked) {
    if (current.includes(collectionId)
      || current.length >= PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS) return
    store.setSearchCollections([...current, collectionId])
  } else {
    store.setSearchCollections(current.filter(id => id !== collectionId))
  }
}

function runSearch() {
  void store.runSearch()
}

/** 上传入口：先选文件，再决定要不要弹首次说明。 */
function openPicker() {
  uploadError.value = ''
  fileInput.value?.click()
}

function onFilePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  // 立即清空 value：这样连续选同一个文件也会再触发 change。
  input.value = ''
  if (!file) return
  pendingFile.value = file
  uploadError.value = checkPrivateKnowledgeFile(file)
  if (uploadError.value) {
    // 本地就能确定不合格：不弹说明、不发请求，直接显示原因。
    noticeVisible.value = false
    return
  }
  if (readPrivateKnowledgeNoticeVersion() !== PRIVATE_KNOWLEDGE_NOTICE_VERSION) {
    noticeVisible.value = true
    return
  }
  void performUpload()
}

/** 用户点「同意并上传」：先记说明版本（同意是用户的动作，与上传是否成功无关），再上传。 */
function confirmNotice() {
  rememberPrivateKnowledgeNoticeVersion(PRIVATE_KNOWLEDGE_NOTICE_VERSION)
  void performUpload()
}

async function performUpload() {
  const file = pendingFile.value
  if (!file) return
  uploading.value = true
  uploadError.value = ''
  try {
    const created = await store.uploadDocument(file)
    if (created) {
      ElMessage.success('已上传，正在解析并建立索引')
      pendingFile.value = null
      noticeVisible.value = false
    }
  } catch (error) {
    // 失败留在弹窗/上传区里显示受控文案，不关弹窗，便于直接重试。
    uploadError.value = privateKnowledgeErrorMessage(error)
  } finally {
    uploading.value = false
  }
}

/** 名称规则是前端软约束（后端为 1–40 字）：避免空白名与超长名。 */
function validateName(value: string): boolean | string {
  const name = (value || '').trim()
  if (!name) return '请填写知识库名称'
  if (name.length > 40) return '名称不超过 40 个字'
  return true
}

async function openCreate() {
  try {
    const result = await ElMessageBox.prompt('给这个知识库起个名字，之后在咨询里按名字选它。', '新建知识库', {
      confirmButtonText: '新建',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：我的体检资料',
      inputValidator: validateName,
    })
    await store.createCollection({ name: String(result.value).trim() })
    ElMessage.success('知识库已创建')
  } catch (error) {
    // 用户取消走的是 reject：区分不了时按取消处理，不弹错误。
    if (error === 'cancel' || error === 'close') return
    if (error instanceof Error && !(error as { code?: string }).code) return
    ElMessage.error(privateKnowledgeErrorMessage(error))
  }
}

async function openRename(item: PrivateKnowledgeCollection) {
  try {
    const result = await ElMessageBox.prompt('改名只影响显示，不移除任何文档。', '重命名知识库', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: item.name,
      inputValidator: validateName,
    })
    await store.renameCollection(item.id, { name: String(result.value).trim() })
    ElMessage.success('名称已更新')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error instanceof Error && !(error as { code?: string }).code) return
    ElMessage.error(privateKnowledgeErrorMessage(error))
  }
}

async function removeCollection(item: PrivateKnowledgeCollection) {
  try {
    await ElMessageBox.confirm(
      '删除知识库会连同其中的全部文档一起删除，正文、索引与词项都会被清理且无法恢复。确定删除吗？',
      '删除知识库',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    await store.removeCollection(item.id)
    ElMessage.success('知识库及其中文档已删除')
  } catch (error) {
    ElMessage.error(privateKnowledgeErrorMessage(error))
  }
}

async function retryDocument(document: PrivateKnowledgeDocument) {
  try {
    await store.retryDocument(document.id)
    ElMessage.success('已重新提交解析')
  } catch (error) {
    ElMessage.error(privateKnowledgeErrorMessage(error))
  }
}

async function removeDocument(document: PrivateKnowledgeDocument) {
  try {
    await ElMessageBox.confirm(
      '删除后这份文档的正文、索引与词项都会清理，无法恢复。确定删除吗？',
      '删除文档',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    await store.removeDocument(document.id)
    ElMessage.success('文档已删除')
  } catch (error) {
    ElMessage.error(privateKnowledgeErrorMessage(error))
  }
}

function statusLabel(status: PrivateKnowledgeDocument['status']) {
  return PRIVATE_KNOWLEDGE_DOCUMENT_STATUS_LABELS[status] || status
}

/** 失败原因只用受控文案：`errorCode` 不在映射里就按「解析失败」讲，不透传服务端原文。 */
function failureText(document: PrivateKnowledgeDocument) {
  const code = document.errorCode || ''
  return PRIVATE_KNOWLEDGE_ERROR_MESSAGES[code]
    || PRIVATE_KNOWLEDGE_ERROR_MESSAGES.PRIVATE_KNOWLEDGE_PARSE_FAILED
}

function metaText(document: PrivateKnowledgeDocument) {
  const parts = [privateKnowledgeKindLabel(document.kind), formatAttachmentSize(document.byteSize)]
  if (document.pageCount) parts.push(`${document.pageCount} 页`)
  else if (document.charCount) parts.push(`约 ${document.charCount} 字`)
  if (document.chunkCount) parts.push(`${document.chunkCount} 个片段`)
  parts.push(new Date(document.updatedAt || document.createdAt).toLocaleString('zh-CN'))
  return parts.join(' · ')
}
</script>

<template>
  <main class="private-knowledge-page">
    <h1>我的知识库</h1>
    <p class="page-intro">
      把你手上的资料（体检报告、出院小结、化验单说明等）存进来，之后在智能咨询里选中它，
      就能让回答对照你自己的资料来解释。
    </p>
    <p class="scope-hint" role="note">{{ PRIVATE_KNOWLEDGE_SCOPE_HINT }}</p>
    <p class="boundary-hint">{{ PRIVATE_KNOWLEDGE_BOUNDARY_HINT }}</p>

    <el-alert
      v-if="store.error"
      class="load-error"
      :title="store.error"
      type="error"
      :closable="false"
    />
    <el-button v-if="store.error" @click="reload">重新加载</el-button>
    <p v-if="store.loading" role="status">正在加载知识库…</p>

    <div v-if="!store.loading && !store.error" class="knowledge-columns">
      <section class="collections" aria-label="知识库列表">
        <div class="section-head">
          <h2>知识库（{{ store.activeCollections.length }}/{{ PRIVATE_KNOWLEDGE_MAX_COLLECTIONS }}）</h2>
          <el-button
            type="primary"
            size="small"
            class="create-collection"
            :disabled="collectionsAtLimit"
            @click="openCreate"
          >
            新建知识库
          </el-button>
        </div>
        <p v-if="collectionsAtLimit" class="limit-hint" role="note">
          已达上限（最多 {{ PRIVATE_KNOWLEDGE_MAX_COLLECTIONS }} 个）：先删掉不用的知识库再新建。
        </p>
        <p v-if="!store.collections.length" class="collections-empty">
          还没有知识库：先新建一个，再往里上传文档。
        </p>
        <ul v-else class="collections-list">
          <li
            v-for="item in store.collections"
            :key="item.id"
            class="collection-item"
            :class="{ selected: item.id === store.currentCollectionId }"
          >
            <button
              type="button"
              class="collection-select"
              :aria-pressed="item.id === store.currentCollectionId"
              :aria-label="`查看知识库 ${item.name}`"
              @click="store.selectCollection(item.id)"
            >
              <span class="collection-name">{{ item.name }}</span>
              <span class="collection-meta">{{ item.documentCount }} 份文档</span>
            </button>
            <div class="collection-actions">
              <el-button text size="small" class="rename-collection" :disabled="!!store.busyId" @click="openRename(item)">改名</el-button>
              <el-button
                text
                size="small"
                type="danger"
                class="remove-collection"
                :loading="store.busyId === item.id"
                :disabled="!!store.busyId && store.busyId !== item.id"
                @click="removeCollection(item)"
              >
                删除
              </el-button>
            </div>
          </li>
        </ul>
      </section>

      <section class="documents" aria-label="文档列表">
        <template v-if="store.currentCollection">
          <div class="section-head">
            <h2>{{ store.currentCollection.name }} 的文档</h2>
            <div class="upload-actions">
              <input
                ref="fileInput"
                class="file-input"
                type="file"
                :accept="PRIVATE_KNOWLEDGE_ACCEPT"
                aria-label="选择要上传的文档"
                @change="onFilePicked"
              />
              <el-button
                type="primary"
                size="small"
                class="upload-document"
                :disabled="uploading"
                @click="openPicker"
              >
                上传文档
              </el-button>
            </div>
          </div>
          <p class="upload-hint">{{ PRIVATE_KNOWLEDGE_NOTICE_SHORT }}</p>
          <p class="format-hint">
            支持 PDF / Word / PPT / TXT / Markdown，单个文件不超过 {{ maxSizeText }}；图片不在这里处理。
          </p>
          <el-alert
            v-if="uploadError"
            class="upload-error"
            :title="uploadError"
            type="error"
            :closable="false"
          />

          <p v-if="store.documentsLoading" role="status">正在加载文档…</p>
          <el-alert
            v-if="store.documentsError"
            class="documents-error"
            :title="store.documentsError"
            type="error"
            :closable="false"
          />
          <p v-if="!store.documentsLoading && !store.documentsError && !store.documents.length" class="documents-empty">
            这个知识库还没有文档。
          </p>
          <p v-if="store.documentSummary.total" class="documents-summary" role="status">
            共 {{ store.documentSummary.total }} 份：可用 {{ store.documentSummary.ready }}<template
              v-if="store.documentSummary.pending"
            > · 处理中 {{ store.documentSummary.pending }}</template><template
              v-if="store.documentSummary.failed"
            > · 失败 {{ store.documentSummary.failed }}</template>
          </p>
          <ul v-if="store.documents.length" class="documents-list">
            <li v-for="document in store.documents" :key="document.id" class="document-item">
              <div class="document-main">
                <div class="document-title">
                  <strong class="document-name">{{ document.displayName }}</strong>
                  <span class="document-status" :class="`status-${document.status}`">
                    {{ statusLabel(document.status) }}
                  </span>
                </div>
                <span class="document-meta">{{ metaText(document) }}</span>
                <p v-if="document.status === 'failed'" class="document-failure">
                  {{ failureText(document) }}
                </p>
              </div>
              <div class="document-actions">
                <el-button
                  v-if="document.status === 'failed'"
                  text
                  size="small"
                  class="retry-document"
                  :loading="store.busyId === document.id"
                  :disabled="!!store.busyId && store.busyId !== document.id"
                  @click="retryDocument(document)"
                >
                  重试
                </el-button>
                <el-button
                  text
                  size="small"
                  type="danger"
                  class="remove-document"
                  :loading="store.busyId === document.id && document.status !== 'failed'"
                  :disabled="!!store.busyId && store.busyId !== document.id"
                  @click="removeDocument(document)"
                >
                  删除
                </el-button>
              </div>
            </li>
          </ul>
        </template>
        <p v-else class="documents-empty">先选择或新建一个知识库。</p>
      </section>

      <!-- P2：只检索、不进对话；范围是用户显式勾选的 1–3 个库，结果只是他自己资料的命中。 -->
      <section class="search" aria-label="在知识库中搜索">
        <div class="section-head">
          <h2>在知识库中搜索</h2>
          <span class="search-limit">{{ PRIVATE_KNOWLEDGE_SEARCH_LIMIT_HINT }}</span>
        </div>
        <p class="search-hint">{{ PRIVATE_KNOWLEDGE_SEARCH_HINT }}</p>
        <fieldset class="search-scope">
          <legend>检索范围（最多 {{ PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS }} 个）</legend>
          <label v-for="item in store.activeCollections" :key="item.id" class="scope-option">
            <input
              type="checkbox"
              :checked="store.searchCollectionIds.includes(item.id)"
              :disabled="!store.searchCollectionIds.includes(item.id)
                && store.searchCollectionIds.length >= PRIVATE_KNOWLEDGE_SEARCH_MAX_COLLECTIONS"
              @change="toggleSearchScope(item.id, ($event.target as HTMLInputElement).checked)"
            />
            <span>{{ item.name }}</span>
          </label>
          <p v-if="!store.activeCollections.length" class="scope-required">还没有可以检索的知识库。</p>
          <p v-else-if="!store.searchCollectionIds.length" class="scope-required" role="note">
            {{ PRIVATE_KNOWLEDGE_SEARCH_SCOPE_REQUIRED }}
          </p>
        </fieldset>
        <div class="search-bar">
          <el-input
            v-model="store.searchQuery"
            class="search-input"
            :maxlength="PRIVATE_KNOWLEDGE_SEARCH_MAX_QUERY_LENGTH"
            placeholder="例如：我的体检报告里血糖和糖化血红蛋白是多少"
            aria-label="搜索内容"
            @keyup.enter="runSearch"
          />
          <el-button
            type="primary"
            class="run-search"
            :loading="store.searching"
            :disabled="!store.canSearch"
            @click="runSearch"
          >
            搜索
          </el-button>
          <el-button
            v-if="store.searchQuery || store.searchPerformed"
            text
            class="clear-search"
            @click="store.clearSearch()"
          >
            清空
          </el-button>
        </div>
        <el-alert
          v-if="store.searchError"
          class="search-error"
          :title="store.searchError"
          type="error"
          :closable="false"
        />
        <p v-if="store.searching" role="status">正在检索你勾选的知识库…</p>
        <p
          v-else-if="store.searchPerformed && !store.searchResults.length && !store.searchError"
          class="search-empty"
        >
          {{ PRIVATE_KNOWLEDGE_SEARCH_EMPTY }}
        </p>
        <ol v-if="store.searchResults.length" class="search-results">
          <li
            v-for="hit in store.searchResults"
            :key="`${hit.documentId}-${hit.referenceNumber}`"
            class="search-hit"
          >
            <div class="hit-head">
              <strong class="hit-document">{{ hit.documentName }}</strong>
              <span class="hit-similarity">{{ privateKnowledgeSimilarityLabel(hit.similarity) }}</span>
            </div>
            <span class="hit-source">
              {{ hit.collectionName }}<template v-if="hit.locator"> · {{ hit.locator }}</template>
            </span>
            <p class="hit-excerpt">{{ hit.excerpt }}</p>
          </li>
        </ol>
      </section>
    </div>

    <PrivateKnowledgeNoticeDialog
      v-model="noticeVisible"
      :file-name="pendingFile?.name"
      :submitting="uploading"
      :error="uploadError"
      @confirm="confirmNotice"
    />
  </main>
</template>

<style scoped>
.private-knowledge-page { max-width: 1080px; margin: auto; padding: 40px; }
h1 { font-size: 25px; font-weight: 600; margin: 0 0 8px; }
.page-intro { margin: 0 0 8px; color: #8a99a8; font-size: 14px; line-height: 1.8; }
.scope-hint { margin: 0 0 6px; color: #2f5876; font-size: 13px; font-weight: 600; }
.boundary-hint { margin: 0 0 18px; color: #8a99a8; font-size: 12px; line-height: 1.8; }
.load-error, .upload-error, .documents-error { margin-bottom: 12px; }
.knowledge-columns { display: grid; grid-template-columns: minmax(240px, 320px) 1fr; gap: 24px; align-items: start; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h2 { font-size: 16px; font-weight: 600; color: #4b6277; margin: 0; }
.limit-hint { margin: 8px 0 0; color: #b26a00; font-size: 12px; }
.collections-empty, .documents-empty {
  margin-top: 16px; padding: 28px 20px; border: 1px dashed #dce5ee; border-radius: 14px;
  color: #8a99a8; font-size: 13px; text-align: center;
}
.collections-list, .documents-list { list-style: none; margin: 14px 0 0; padding: 0; }
.collection-item {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px; margin-bottom: 8px;
  border: 1px solid #e5edf4; border-radius: 12px; background: #fff;
}
.collection-item.selected { border-color: #237ac2; background: #f4f9ff; }
.collection-select {
  flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px;
  background: none; border: 0; padding: 0; text-align: left; cursor: pointer; font: inherit;
}
.collection-name { color: #2f5876; font-size: 14px; font-weight: 600; word-break: break-all; }
.collection-meta { color: #8a99a8; font-size: 12px; }
.collection-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
.upload-actions { display: flex; align-items: center; gap: 8px; }
.file-input { display: none; }
.upload-hint { margin: 10px 0 4px; color: #4b6277; font-size: 12px; line-height: 1.8; }
.format-hint { margin: 0 0 14px; color: #8a99a8; font-size: 12px; line-height: 1.8; }
.documents-summary { margin: 0 0 8px; color: #4b6277; font-size: 12px; }
.document-item {
  display: flex; align-items: flex-start; gap: 12px; padding: 14px 0; border-bottom: 1px solid #e5edf4;
}
.document-main { flex: 1; min-width: 0; }
.document-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.document-name { color: #2f5876; font-size: 14px; word-break: break-all; }
.document-status { border-radius: 999px; padding: 1px 8px; font-size: 12px; background: #eef4fa; color: #4b6277; }
.document-status.status-ready { background: #e8f6ee; color: #237a4b; }
.document-status.status-failed { background: #fdeceb; color: #b3261e; }
.document-meta { display: block; margin-top: 6px; color: #8a99a8; font-size: 12px; line-height: 1.8; }
.document-failure { margin: 8px 0 0; color: #b3261e; font-size: 12px; line-height: 1.8; }
.document-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
/* P2 搜索区：跨满两列，避免被挤进左侧窄栏。 */
.search { grid-column: 1 / -1; margin-top: 8px; padding-top: 20px; border-top: 1px solid #e5edf4; }
.search-limit { color: #8a99a8; font-size: 12px; }
.search-hint { margin: 10px 0 14px; color: #4b6277; font-size: 12px; line-height: 1.8; }
.search-scope { margin: 0 0 12px; padding: 10px 12px; border: 1px solid #e5edf4; border-radius: 12px; }
.search-scope legend { padding: 0 6px; color: #8a99a8; font-size: 12px; }
.scope-option { display: inline-flex; align-items: center; gap: 6px; margin: 0 14px 6px 0; color: #2f5876; font-size: 13px; }
.scope-required { margin: 6px 0 0; color: #b26a00; font-size: 12px; }
.search-bar { display: flex; align-items: center; gap: 8px; }
.search-input { flex: 1; }
.search-error { margin-top: 12px; }
.search-empty { margin: 12px 0 0; color: #8a99a8; font-size: 13px; }
.search-results { list-style: none; margin: 14px 0 0; padding: 0; }
.search-hit { padding: 12px 0; border-bottom: 1px solid #e5edf4; }
.hit-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.hit-document { color: #2f5876; font-size: 14px; word-break: break-all; }
.hit-similarity { border-radius: 999px; padding: 1px 8px; background: #eef4fa; color: #4b6277; font-size: 12px; }
.hit-source { display: block; margin-top: 4px; color: #8a99a8; font-size: 12px; }
.hit-excerpt { margin: 8px 0 0; color: #4b6277; font-size: 13px; line-height: 1.8; }
@media (max-width: 900px) {
  .knowledge-columns { grid-template-columns: 1fr; }
  .private-knowledge-page { padding: 24px 16px; }
}
</style>