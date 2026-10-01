import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import PrivateKnowledgeView from './PrivateKnowledgeView.vue'
import { privateKnowledgeApi } from '../api/privateKnowledge'
import { ApiError } from '../api/http'
import { usePrivateKnowledgeStore } from '../stores/privateKnowledge'
import { PRIVATE_KNOWLEDGE_NOTICE_STORAGE_KEY } from '../stores/composerHints'
import {
  type PrivateKnowledgeCollection,
  type PrivateKnowledgeDocument,
} from '../types/privateKnowledge'
import {
  PRIVATE_KNOWLEDGE_MAX_COLLECTIONS,
  PRIVATE_KNOWLEDGE_NOTICE_VERSION,
} from '../types/privateKnowledgeUi'

/**
 * 「我的知识库」管理页与状态层的专项测试（P1）。
 *
 * **只验证「拿到某种响应后页面渲染成什么样、发出什么请求」**：接口模块整体被 mock，
 * 没有真实后端参与。真实链路要等 Codex 的 `private_knowledge*` 落地后再单独验，见
 * `BROWSER_ACCEPTANCE.md`。
 */
vi.mock('../api/privateKnowledge', () => ({
  privateKnowledgeApi: {
    collections: vi.fn(),
    createCollection: vi.fn(),
    updateCollection: vi.fn(),
    removeCollection: vi.fn(),
    documents: vi.fn(),
    upload: vi.fn(),
    getDocument: vi.fn(),
    retryDocument: vi.fn(),
    removeDocument: vi.fn(),
    search: vi.fn(),
  },
}))

function makeCollection(
  overrides: Partial<PrivateKnowledgeCollection> = {},
): PrivateKnowledgeCollection {
  return {
    id: 'col-1',
    name: '我的体检资料',
    description: null,
    status: 'active',
    documentCount: 2,
    createdAt: '2026-10-01T00:00:00Z',
    updatedAt: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

function makeDocument(
  overrides: Partial<PrivateKnowledgeDocument> = {},
): PrivateKnowledgeDocument {
  return {
    id: 'doc-1',
    collectionId: 'col-1',
    displayName: '体检报告.pdf',
    kind: 'pdf',
    byteSize: 2 * 1024 * 1024,
    pageCount: 3,
    charCount: 12_000,
    chunkCount: 8,
    parserVersion: 'parser-v1',
    indexVersion: 'index-v1',
    status: 'ready',
    createdAt: '2026-10-01T00:00:00Z',
    updatedAt: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

function pdfFile(name = '体检报告.pdf') {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

beforeEach(() => {
  vi.resetAllMocks()
  window.localStorage.clear()
  setActivePinia(createPinia())
  vi.mocked(privateKnowledgeApi.collections).mockResolvedValue([makeCollection()])
  vi.mocked(privateKnowledgeApi.documents).mockResolvedValue([
    makeDocument(),
    makeDocument({
      id: 'doc-2',
      displayName: '出院小结.docx',
      kind: 'docx',
      status: 'failed',
      errorCode: 'PRIVATE_KNOWLEDGE_PARSE_FAILED',
    }),
  ])
})

afterEach(() => {
  document.body.innerHTML = ''
})

async function mountView() {
  const wrapper = mount(PrivateKnowledgeView, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

/** 选中文件：jsdom 不能直接给 input 赋 files，只能自己定义。 */
async function pickFile(wrapper: VueWrapper, file: File) {
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

async function clickSelector(selector: string) {
  const target = document.querySelector<HTMLButtonElement>(selector)
  expect(target, `页面上找不到 ${selector}`).toBeTruthy()
  target!.click()
  await flushPromises()
}

async function clickText(text: string) {
  const target = Array.from(document.querySelectorAll('button'))
    .find(button => (button.textContent || '').includes(text))
  expect(target, `页面上找不到文案为「${text}」的按钮`).toBeTruthy()
  target!.click()
  await flushPromises()
}

function noticeDialogText() {
  return document.querySelector('.private-knowledge-notice-dialog')?.textContent || ''
}

async function acceptNotice() {
  const checkbox = document.querySelector<HTMLInputElement>(
    '.private-knowledge-notice-dialog__agree input',
  )
  expect(checkbox, '说明弹窗里应当有同意勾选框').toBeTruthy()
  checkbox!.click()
  await flushPromises()
}

describe('我的知识库管理页', () => {
  it('加载后展示知识库、文档数量与「不会自动用于所有对话」', async () => {
    const wrapper = await mountView()

    expect(privateKnowledgeApi.collections).toHaveBeenCalledTimes(1)
    expect(privateKnowledgeApi.documents).toHaveBeenCalledWith('col-1')
    expect(document.body.textContent).toContain('我的体检资料')
    expect(document.body.textContent).toContain('2 份文档')
    expect(document.body.textContent).toContain('体检报告.pdf')
    expect(document.body.textContent).toContain('PDF')
    expect(document.body.textContent).toContain('3 页')
    // 产品要求写在明面上：不选就不会被检索。
    expect(document.body.textContent).toContain('不会自动用于所有对话')
    wrapper.unmount()
  })

  it('没有知识库时给出空态，不请求任何文档', async () => {
    vi.mocked(privateKnowledgeApi.collections).mockResolvedValue([])
    const wrapper = await mountView()

    expect(document.body.textContent).toContain('还没有知识库')
    expect(privateKnowledgeApi.documents).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('点击另一个知识库切换到它的文档列表', async () => {
    vi.mocked(privateKnowledgeApi.collections).mockResolvedValue([
      makeCollection(),
      makeCollection({ id: 'col-2', name: '第二个库', documentCount: 0 }),
    ])
    const wrapper = await mountView()

    await clickSelector('button[aria-label="查看知识库 第二个库"]')
    expect(privateKnowledgeApi.documents).toHaveBeenLastCalledWith('col-2')
    expect(document.body.textContent).toContain('第二个库 的文档')
    wrapper.unmount()
  })

  it('列表加载失败显示受控中文，并可以重新加载', async () => {
    vi.mocked(privateKnowledgeApi.collections).mockRejectedValueOnce(
      new ApiError('raw upstream detail', 'PRIVATE_KNOWLEDGE_COLLECTION_NOT_FOUND', 404),
    )
    const wrapper = await mountView()

    expect(document.body.textContent).toContain('这个知识库不存在或已被删除')
    expect(document.body.textContent).not.toContain('raw upstream detail')
    await clickText('重新加载')
    expect(privateKnowledgeApi.collections).toHaveBeenCalledTimes(2)
    expect(document.body.textContent).toContain('我的体检资料')
    wrapper.unmount()
  })

  it('达到数量上限后禁用新建并说明原因', async () => {
    vi.mocked(privateKnowledgeApi.collections).mockResolvedValue(
      Array.from({ length: PRIVATE_KNOWLEDGE_MAX_COLLECTIONS }, (_, index) =>
        makeCollection({ id: `col-${index}`, name: `库 ${index}` })),
    )
    const wrapper = await mountView()

    expect(document.body.textContent).toContain(
      `已达上限（最多 ${PRIVATE_KNOWLEDGE_MAX_COLLECTIONS} 个）`,
    )
    expect(document.querySelector<HTMLButtonElement>('.create-collection')?.disabled).toBe(true)
    wrapper.unmount()
  })

  it('新建知识库后自动选中新库', async () => {
    const created = makeCollection({ id: 'col-9', name: '新库', documentCount: 0 })
    vi.mocked(privateKnowledgeApi.createCollection).mockResolvedValue(created)
    vi.mocked(privateKnowledgeApi.collections)
      .mockResolvedValueOnce([makeCollection()])
      .mockResolvedValue([makeCollection(), created])
    vi.mocked(privateKnowledgeApi.documents).mockResolvedValue([])
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValueOnce(
      { value: '新库', action: 'confirm' } as Awaited<ReturnType<typeof ElMessageBox.prompt>>,
    )
    const wrapper = await mountView()

    await clickSelector('.create-collection')
    expect(privateKnowledgeApi.createCollection).toHaveBeenCalledWith('新库', undefined)
    await flushPromises()
    expect(usePrivateKnowledgeStore().currentCollectionId).toBe('col-9')
    expect(document.body.textContent).toContain('新库 的文档')
    wrapper.unmount()
  })

  it('改名走 PATCH 并更新列表显示', async () => {
    vi.mocked(privateKnowledgeApi.updateCollection).mockResolvedValue(
      makeCollection({ name: '改名后' }),
    )
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValueOnce(
      { value: '改名后', action: 'confirm' } as Awaited<ReturnType<typeof ElMessageBox.prompt>>,
    )
    const wrapper = await mountView()

    await clickSelector('.rename-collection')
    expect(privateKnowledgeApi.updateCollection).toHaveBeenCalledWith('col-1', '改名后', undefined)
    expect(document.body.textContent).toContain('改名后')
    wrapper.unmount()
  })

  it('删除知识库必须确认，取消时不发请求', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    const wrapper = await mountView()

    await clickSelector('.remove-collection')
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(privateKnowledgeApi.removeCollection).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('确认删除后知识库连同文档一起从列表移除', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(
      'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>,
    )
    vi.mocked(privateKnowledgeApi.removeCollection).mockResolvedValue(undefined)
    const wrapper = await mountView()

    await clickSelector('.remove-collection')
    expect(privateKnowledgeApi.removeCollection).toHaveBeenCalledWith('col-1')
    await flushPromises()
    expect(document.body.textContent).toContain('知识库及其中文档已删除')
    expect(document.body.textContent).not.toContain('我的体检资料')
    wrapper.unmount()
  })

  it('删除文档必须确认，取消时不发请求', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    const wrapper = await mountView()

    await clickSelector('.remove-document')
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(privateKnowledgeApi.removeDocument).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('确认删除后文档从列表移除，数量同步更新', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(
      'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>,
    )
    vi.mocked(privateKnowledgeApi.removeDocument).mockResolvedValue(undefined)
    const wrapper = await mountView()

    await clickSelector('.remove-document')
    expect(privateKnowledgeApi.removeDocument).toHaveBeenCalledWith('doc-1')
    await flushPromises()
    expect(document.body.textContent).toContain('文档已删除')
    expect(document.body.textContent).not.toContain('体检报告.pdf')
    expect(document.body.textContent).toContain('1 份文档')
    wrapper.unmount()
  })

  it('文档状态与失败原因如实展示，失败可以重试', async () => {
    vi.mocked(privateKnowledgeApi.retryDocument).mockResolvedValue(
      makeDocument({ id: 'doc-2', displayName: '出院小结.docx', kind: 'docx', status: 'indexing' }),
    )
    const wrapper = await mountView()

    expect(document.body.textContent).toContain('可用')
    expect(document.body.textContent).toContain('处理失败')
    expect(document.body.textContent).toContain('解析失败，可以重试')
    await clickSelector('.retry-document')
    expect(privateKnowledgeApi.retryDocument).toHaveBeenCalledWith('doc-2')
    await flushPromises()
    expect(document.body.textContent).toContain('建立索引')
    expect(document.body.textContent).not.toContain('处理失败')
    wrapper.unmount()
  })

  it('处理中的文档按单个文档轮询，没有处理中就不再问', async () => {
    vi.mocked(privateKnowledgeApi.documents)
      .mockResolvedValue([makeDocument({ status: 'indexing' })])
    vi.mocked(privateKnowledgeApi.getDocument).mockResolvedValue(
      makeDocument({ status: 'ready' }),
    )
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()

    expect(document.body.textContent).toContain('建立索引')
    await store.refreshPendingDocuments()
    await flushPromises()
    expect(privateKnowledgeApi.getDocument).toHaveBeenCalledWith('doc-1')
    expect(document.body.textContent).toContain('可用')

    await store.refreshPendingDocuments()
    expect(privateKnowledgeApi.getDocument).toHaveBeenCalledTimes(1)
    expect(store.polling).toBe(false)
    wrapper.unmount()
  })

  it('离开页面时停掉轮询', async () => {
    vi.mocked(privateKnowledgeApi.documents)
      .mockResolvedValue([makeDocument({ status: 'indexing' })])
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()

    expect(store.polling).toBe(true)
    wrapper.unmount()
    expect(store.polling).toBe(false)
  })

  it('首次上传先弹说明，未同意不上传，同意后上传并记下说明版本', async () => {
    vi.mocked(privateKnowledgeApi.upload).mockResolvedValue(
      makeDocument({ status: 'indexing' }),
    )
    const wrapper = await mountView()

    await pickFile(wrapper, pdfFile())
    expect(privateKnowledgeApi.upload).not.toHaveBeenCalled()
    expect(noticeDialogText()).toContain('不保存原件')
    expect(noticeDialogText()).toContain('不会自动用于所有对话')

    // 未勾选同意时按钮不可用，点了也不发请求。
    await clickText('同意并上传')
    expect(privateKnowledgeApi.upload).not.toHaveBeenCalled()

    await acceptNotice()
    await clickText('同意并上传')
    expect(privateKnowledgeApi.upload).toHaveBeenCalledWith('col-1', expect.any(File))
    expect(window.localStorage.getItem(PRIVATE_KNOWLEDGE_NOTICE_STORAGE_KEY))
      .toBe(PRIVATE_KNOWLEDGE_NOTICE_VERSION)
    expect(document.body.textContent).toContain('已上传，正在解析并建立索引')
    wrapper.unmount()
  })

  it('已确认过说明时直接上传，不再弹说明', async () => {
    window.localStorage.setItem(
      PRIVATE_KNOWLEDGE_NOTICE_STORAGE_KEY,
      PRIVATE_KNOWLEDGE_NOTICE_VERSION,
    )
    vi.mocked(privateKnowledgeApi.upload).mockResolvedValue(
      makeDocument({ status: 'indexing' }),
    )
    const wrapper = await mountView()

    await pickFile(wrapper, pdfFile())
    expect(privateKnowledgeApi.upload).toHaveBeenCalledTimes(1)
    expect(noticeDialogText()).not.toContain('不保存原件')
    wrapper.unmount()
  })

  it('不支持的扩展名在浏览器里就被拦下，不发请求也不弹说明', async () => {
    const wrapper = await mountView()

    await pickFile(wrapper, new File(['x'], 'ct.png', { type: 'image/png' }))
    expect(privateKnowledgeApi.upload).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('暂不支持图片')
    expect(noticeDialogText()).not.toContain('不保存原件')
    wrapper.unmount()
  })

  it('超过体积上限的文件在本地被拦下', async () => {
    const wrapper = await mountView()
    const big = pdfFile('很大.pdf')
    Object.defineProperty(big, 'size', { value: 31 * 1024 * 1024 })

    await pickFile(wrapper, big)
    expect(privateKnowledgeApi.upload).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('单个文件不能超过 30 MB')
    wrapper.unmount()
  })

  it('服务端的受控错误码映射成中文，不透传原文', async () => {
    vi.mocked(privateKnowledgeApi.upload).mockRejectedValue(
      new ApiError('OCR worker crashed', 'PRIVATE_KNOWLEDGE_DOCUMENT_UNSUPPORTED', 422),
    )
    const wrapper = await mountView()

    await pickFile(wrapper, pdfFile())
    await acceptNotice()
    await clickText('同意并上传')
    expect(document.body.textContent).toContain('这个文件类型暂不支持')
    expect(document.body.textContent).not.toContain('OCR worker crashed')
    wrapper.unmount()
  })

  // ---- P2：知识库内搜索 ----

  it('搜索只查勾选的库，命中按相关度展示（P2）', async () => {
    vi.mocked(privateKnowledgeApi.search).mockResolvedValue([
      {
        referenceNumber: 1,
        collectionId: 'col-1',
        collectionName: '我的体检资料',
        documentId: 'doc-1',
        documentName: '体检报告.pdf',
        locator: '第 1 页 第 2 段',
        excerpt: '空腹血糖 6.1 mmol/L',
        similarity: 0.83,
      },
    ])
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()
    // 默认范围就是当前库。
    expect(store.searchCollectionIds).toEqual(['col-1'])

    store.searchQuery = '血糖'
    await flushPromises()
    await wrapper.get('.run-search').trigger('click')
    await flushPromises()

    expect(privateKnowledgeApi.search).toHaveBeenCalledWith({
      query: '血糖',
      collectionIds: ['col-1'],
      limit: 5,
    })
    expect(document.body.textContent).toContain('体检报告.pdf')
    expect(document.body.textContent).toContain('空腹血糖 6.1 mmol/L')
    expect(document.body.textContent).toContain('相关度 83%')
    expect(document.body.textContent).toContain('第 1 页 第 2 段')
    wrapper.unmount()
  })

  it('没勾选任何库时不能搜索，并说明原因', async () => {
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()
    store.setSearchCollections([])
    store.searchQuery = '血糖'
    await flushPromises()

    expect(store.canSearch).toBe(false)
    expect(document.body.textContent).toContain('请先勾选要检索的知识库')
    await wrapper.get('.run-search').trigger('click')
    expect(privateKnowledgeApi.search).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('最多只能勾选 3 个库，第 4 个复选框是禁用的', async () => {
    vi.mocked(privateKnowledgeApi.collections).mockResolvedValue([
      makeCollection(),
      makeCollection({ id: 'col-2', name: '出院资料' }),
      makeCollection({ id: 'col-3', name: '化验单' }),
      makeCollection({ id: 'col-4', name: '影像说明' }),
    ])
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()
    store.setSearchCollections(['col-1', 'col-2', 'col-3'])
    await flushPromises()

    const boxes = wrapper.findAll('.scope-option input[type="checkbox"]')
    expect(boxes.length).toBe(4)
    expect((boxes[3].element as HTMLInputElement).disabled).toBe(true)
    expect(store.searchCollectionIds).toEqual(['col-1', 'col-2', 'col-3'])
    wrapper.unmount()
  })

  it('命中为空时说明检索范围只覆盖勾选的库', async () => {
    vi.mocked(privateKnowledgeApi.search).mockResolvedValue([])
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()
    store.searchQuery = '不存在的词'
    await flushPromises()
    await wrapper.get('.run-search').trigger('click')
    await flushPromises()

    expect(document.body.textContent).toContain('在你勾选的知识库里没有找到相关内容')
    wrapper.unmount()
  })

  it('搜索失败只显示受控中文，不透传服务端原文', async () => {
    vi.mocked(privateKnowledgeApi.search).mockRejectedValue(
      new ApiError('qdrant timeout at shard 3', 'PRIVATE_KNOWLEDGE_SELECTION_INVALID', 422),
    )
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()
    store.searchQuery = '血糖'
    await flushPromises()
    await wrapper.get('.run-search').trigger('click')
    await flushPromises()

    expect(document.body.textContent).toContain('选择的知识库无效，请重新选择')
    expect(document.body.textContent).not.toContain('qdrant timeout')
    wrapper.unmount()
  })

  it('切换检索范围会清掉上一轮命中，避免旧结果被当成新结果', async () => {
    vi.mocked(privateKnowledgeApi.search).mockResolvedValue([
      {
        referenceNumber: 1,
        collectionId: 'col-1',
        collectionName: '我的体检资料',
        documentId: 'doc-1',
        documentName: '体检报告.pdf',
        locator: '第 1 页',
        excerpt: '空腹血糖 6.1 mmol/L',
        similarity: 0.9,
      },
    ])
    const wrapper = await mountView()
    const store = usePrivateKnowledgeStore()
    store.searchQuery = '血糖'
    await flushPromises()
    await wrapper.get('.run-search').trigger('click')
    await flushPromises()
    expect(store.searchResults.length).toBe(1)

    store.setSearchCollections([])
    await flushPromises()
    expect(store.searchResults).toEqual([])
    expect(store.searchPerformed).toBe(false)
    wrapper.unmount()
  })
})