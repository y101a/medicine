import { expect, test, type Page, type Route } from '@playwright/test'
import { API_GLOB, installApiStubs, measureOverflow, settle, waitForRendered } from './support'

/**
 * 「我的知识库」管理页的浏览器验收（P1）。
 *
 * **口径**：只起 Vite，所有 `/api/v1/**` 走 `page.route` 桩，**没有真实后端参与**，
 * 因此这里证明的是「前端拿到某种响应后渲染成什么样、发出什么请求」，
 * **不证明真实链路可用**——后端 `private_knowledge*` 尚未落地，见 `BROWSER_ACCEPTANCE.md`。
 *
 * 与其它规格不同，私人知识库是多步写操作（新建 → 上传 → 轮询 → 删除），所以这里在
 * 默认真的基础上加一层**有状态桩**：它自己维护库与文档，按轮询次数推进状态，
 * 并对未匹配的路径 `route.fallback()` 交还给默认桩。桩只在本文件内，不改公共 `support.ts`。
 */

interface StubCollection {
  id: string
  name: string
  description: string | null
  status: string
  documentCount: number
  createdAt: string
  updatedAt: string
}

interface StubDocument {
  id: string
  collectionId: string
  displayName: string
  kind: string
  byteSize: number
  pageCount: number | null
  status: string
  errorCode?: string | null
  createdAt: string
  updatedAt: string
}

const NOW = '2026-10-01T09:00:00Z'

function collection(id: string, name: string, documentCount: number): StubCollection {
  return { id, name, description: null, status: 'active', documentCount, createdAt: NOW, updatedAt: NOW }
}

function document(
  id: string,
  collectionId: string,
  displayName: string,
  status: string,
  extra: Partial<StubDocument> = {},
): StubDocument {
  return {
    id,
    collectionId,
    displayName,
    kind: displayName.split('.').pop() || 'pdf',
    byteSize: 2 * 1024 * 1024,
    pageCount: 3,
    status,
    errorCode: null,
    createdAt: NOW,
    updatedAt: NOW,
    ...extra,
  }
}

interface KnowledgeStubState {
  collections: StubCollection[]
  documents: Map<string, StubDocument[]>
  /** 上传请求的原始报文，用来核对 multipart 字段（不含 userId）。 */
  uploadBodies: string[]
  uploadContentTypes: string[]
  /** 搜索请求的 JSON 报文（P2），用来核对只发 query / collectionIds / limit。 */
  searchBodies: string[]
  /** 默认桩里没配置到的接口（与 `installApiStubs` 返回的是同一个数组）。 */
  unmatched: string[]
}

interface StubOptions {
  collections?: StubCollection[]
  documents?: Map<string, StubDocument[]>
  /** 让上传返回受控错误码，验证前端映射。 */
  uploadErrorCode?: string
  uploadErrorStatus?: number
  /** 让搜索返回受控错误码（P2），验证前端映射不透传原文。 */
  searchErrorCode?: string
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installKnowledgeStubs(page: Page, options: StubOptions = {}): Promise<KnowledgeStubState> {
  const state: KnowledgeStubState = {
    collections: options.collections ?? [
      collection('col-1', '我的体检资料', 2),
      collection('col-2', '用药记录', 0),
    ],
    documents: options.documents ?? new Map<string, StubDocument[]>([
      ['col-1', [
        document('doc-1', 'col-1', '体检报告.pdf', 'ready'),
        document('doc-2', 'col-1', '出院小结.docx', 'failed', {
          kind: 'docx',
          errorCode: 'PRIVATE_KNOWLEDGE_PARSE_FAILED',
        }),
      ]],
      ['col-2', []],
    ]),
    uploadBodies: [],
    uploadContentTypes: [],
    searchBodies: [],
    unmatched: [],
  }

  // 默认桩先装（登录态、模型列表等都在里面），私人知识库的路径由下面的有状态桩接管。
  // 只装这一次：再装一次默认桩会排在前面，把私人知识库的请求重新变成 404。
  const installed = await installApiStubs(page)
  state.unmatched = installed.unmatched
  await page.route(API_GLOB, async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api/v1', '')
    if (!path.startsWith('/private-knowledge')) return route.fallback()
    const method = request.method()

    const collectionMatch = path.match(/^\/private-knowledge\/collections\/([^/]+)$/)
    const documentsMatch = path.match(/^\/private-knowledge\/collections\/([^/]+)\/documents$/)
    const documentMatch = path.match(/^\/private-knowledge\/documents\/([^/]+)(\/retry)?$/)

    if (path === '/private-knowledge/collections' && method === 'GET') {
      return json(route, 200, { items: state.collections })
    }
    if (path === '/private-knowledge/collections' && method === 'POST') {
      const body = request.postDataJSON() as { name: string }
      const created = collection(`col-${state.collections.length + 1}`, body.name, 0)
      state.collections = [...state.collections, created]
      state.documents.set(created.id, [])
      return json(route, 200, created)
    }
    if (collectionMatch && method === 'PATCH') {
      const id = collectionMatch[1]
      const body = request.postDataJSON() as { name?: string }
      state.collections = state.collections.map(item => (
        item.id === id ? { ...item, name: body.name ?? item.name } : item
      ))
      return json(route, 200, state.collections.find(item => item.id === id))
    }
    if (collectionMatch && method === 'DELETE') {
      const id = collectionMatch[1]
      state.collections = state.collections.filter(item => item.id !== id)
      state.documents.delete(id)
      return json(route, 200, {})
    }
    if (path === '/private-knowledge/search' && method === 'POST') {
      const body = request.postDataJSON() as {
        query: string
        collectionIds: string[]
        limit?: number
      }
      state.searchBodies.push(JSON.stringify(body))
      if (options.searchErrorCode) {
        return json(route, 422, {
          code: options.searchErrorCode,
          // 故意带一段「原始报文」：前端不得把它显示给用户。
          message: 'selection rejected at gateway: shard 3 timeout',
        })
      }
      // 命中只从勾选的那些库里出，且只取 `ready` 的文档，条数受 limit 限制。
      const hits: Array<Record<string, unknown>> = []
      for (const collectionId of body.collectionIds) {
        const collectionName = state.collections.find(item => item.id === collectionId)?.name || ''
        for (const item of state.documents.get(collectionId) || []) {
          if (item.status !== 'ready') continue
          hits.push({
            referenceNumber: hits.length + 1,
            collectionId,
            collectionName,
            documentId: item.id,
            documentName: item.displayName,
            locator: '第 1 页 第 2 段',
            excerpt: `${body.query}：空腹血糖 6.1 mmol/L`,
            similarity: 0.83,
          })
        }
      }
      return json(route, 200, { items: hits.slice(0, Math.min(body.limit ?? 5, 5)) })
    }
    if (documentsMatch && method === 'GET') {
      return json(route, 200, { items: state.documents.get(documentsMatch[1]) || [] })
    }
    if (documentsMatch && method === 'POST') {
      const body = request.postData() || ''
      state.uploadBodies.push(body)
      state.uploadContentTypes.push(request.headers()['content-type'] || '')
      if (options.uploadErrorCode) {
        return json(route, options.uploadErrorStatus ?? 422, {
          code: options.uploadErrorCode,
          // 故意带一段「原始报文」：前端不得把它显示给用户。
          message: 'raw worker trace: OCR exception at line 42',
        })
      }
      const id = documentsMatch[1]
      // 文件名从 multipart 里取，这样桩返回的就是用户真正选的那份。
      const uploadedName = /filename="([^"]*)"/.exec(body)?.[1] || '新上传.pdf'
      const created = document(`doc-${Date.now()}`, id, uploadedName, 'indexing')
      state.documents.set(id, [created, ...(state.documents.get(id) || [])])
      state.collections = state.collections.map(item => (
        item.id === id ? { ...item, documentCount: (state.documents.get(id) || []).length } : item
      ))
      return json(route, 200, created)
    }
    if (documentMatch) {
      const id = documentMatch[1]
      const list = state.documents.get('col-1') || []
      const target = [...list, ...(state.documents.get('col-2') || [])]
        .find(item => item.id === id)
      if (!target) return json(route, 404, { code: 'PRIVATE_KNOWLEDGE_DOCUMENT_NOT_FOUND' })
      if (method === 'POST') {
        // 重试：先回到「建立索引」，下一轮轮询会变成可用。
        const retried = { ...target, status: 'indexing', errorCode: null }
        state.documents.set(target.collectionId, (state.documents.get(target.collectionId) || [])
          .map(item => (item.id === id ? retried : item)))
        return json(route, 200, retried)
      }
      if (method === 'GET') {
        // 轮询：处理中的文档下一轮就绪，页面应从「建立索引」变成「可用」。
        const advanced = target.status === 'indexing'
          ? { ...target, status: 'ready', errorCode: null }
          : target
        state.documents.set(target.collectionId, (state.documents.get(target.collectionId) || [])
          .map(item => (item.id === id ? advanced : item)))
        return json(route, 200, advanced)
      }
      if (method === 'DELETE') {
        state.documents.set(target.collectionId, (state.documents.get(target.collectionId) || [])
          .filter(item => item.id !== id))
        state.collections = state.collections.map(item => (
          item.id === target.collectionId
            ? { ...item, documentCount: (state.documents.get(target.collectionId) || []).length }
            : item
        ))
        return json(route, 200, {})
      }
    }
    return json(route, 404, { message: `e2e 未配置：${method} ${path}` })
  })

  return state
}

async function openPage(page: Page) {
  await page.goto('/app/private-knowledge')
  await settle(page)
  await waitForRendered(page, '.private-knowledge-page')
}

test('侧栏有独立入口，页面明示作用域与格式限制，且没有漏配接口', async ({ page }) => {
  // 装私人知识库桩，否则集合拉不到、文档区与格式说明都不渲染。
  const state = await installKnowledgeStubs(page)
  await page.goto('/app')
  await settle(page)

  const entry = page.locator('a[href="/app/private-knowledge"]')
  await expect(entry, '私人资料必须有独立入口（方案 §8.1）').toBeVisible()
  await entry.click()
  await waitForRendered(page, '.private-knowledge-page')

  await expect(page.locator('.scope-hint')).toContainText('不会自动用于所有对话')
  await expect(page.locator('.boundary-hint')).toContainText('不用于确诊、开药或调整用药')
  await expect(page.locator('.format-hint')).toContainText('PDF / Word / PPT / TXT / Markdown')
  await expect(page.locator('.format-hint')).toContainText('图片不在这里处理')
  /*
   * `/users/me/avatar` 与 `GET /private-knowledge/collections` 已补进公共默认桩（2026-10-03，DSH），
   * 所以这里不再为任何既存缺口开例外：断言回到最严的「一个未配置接口都不能有」，
   * 缺口一旦重新出现，这条用例就会红，而不是只在日志里打一行字。
   */
  expect(state.unmatched, `有未配置的接口：${state.unmatched.join('、')}`).toEqual([])
})

test('空知识库显示空态，新建后出现在列表并被选中', async ({ page }) => {
  await installKnowledgeStubs(page, { collections: [], documents: new Map() })
  await openPage(page)

  await expect(page.locator('.collections-empty')).toContainText('还没有知识库')
  await expect(page.locator('.documents-empty').first()).toContainText('先选择或新建一个知识库')

  await page.locator('.create-collection').click()
  const box = page.locator('.el-message-box')
  await expect(box).toBeVisible()
  await box.locator('input').fill('我的用药记录')
  await box.getByRole('button', { name: '新建' }).click()

  await expect(page.locator('.collection-name', { hasText: '我的用药记录' })).toBeVisible()
  await expect(page.locator('.documents h2')).toContainText('我的用药记录 的文档')
  await expect(page.locator('.documents-empty')).toContainText('这个知识库还没有文档')
})

test('首次上传必须确认说明，同意后上传并按轮询变为可用', async ({ page }) => {
  const state = await installKnowledgeStubs(page)
  await openPage(page)

  await page.locator('.upload-document').click()
  await page.setInputFiles('input[type="file"]', {
    name: '新上传.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 e2e'),
  })

  const dialog = page.locator('.private-knowledge-notice-dialog')
  await expect(dialog, '首次上传应先弹说明').toBeVisible()
  await expect(dialog).toContainText('不保存原件')
  await expect(dialog).toContainText('不会自动用于所有对话')

  const confirm = dialog.getByRole('button', { name: '同意并上传' })
  await expect(confirm, '未勾选同意时不得上传').toBeDisabled()
  // Element Plus 的原生 checkbox 是隐藏的：只能点可见的 label，再核对状态。
  await dialog.locator('.private-knowledge-notice-dialog__agree').click()
  await expect(dialog.getByRole('checkbox')).toBeChecked()
  await expect(confirm).toBeEnabled()
  await confirm.click()

  const row = page.locator('.document-item', { hasText: '新上传.pdf' })
  await expect(row, '上传后应出现在文档列表').toBeVisible()
  await expect(row.locator('.document-status'), '处理中的文档应轮询到可用').toContainText(
    '可用',
    { timeout: 15_000 },
  )

  // 契约核对：multipart 里必须带说明版本，且不得出现 userId。
  const body = state.uploadBodies.at(-1) || ''
  expect(state.uploadContentTypes.at(-1)).toContain('multipart/form-data')
  expect(body).toContain('noticeVersion')
  expect(body, '请求体里不得出现 userId（方案 §7 首行）').not.toContain('userId')
})

test('同一页面第二次上传不再弹说明', async ({ page }) => {
  await installKnowledgeStubs(page)
  await openPage(page)

  await page.locator('.upload-document').click()
  await page.setInputFiles('input[type="file"]', {
    name: '第一份.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 e2e'),
  })
  const dialog = page.locator('.private-knowledge-notice-dialog')
  await dialog.locator('.private-knowledge-notice-dialog__agree').click()
  await dialog.getByRole('button', { name: '同意并上传' }).click()
  await expect(page.locator('.document-item', { hasText: '第一份.pdf' })).toBeVisible()

  await page.locator('.upload-document').click()
  await page.setInputFiles('input[type="file"]', {
    name: '第二份.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 e2e'),
  })
  await expect(page.locator('.document-item', { hasText: '第二份.pdf' })).toBeVisible()
  await expect(dialog).toBeHidden()
})

test('解析失败展示受控原因，重试后变为可用', async ({ page }) => {
  await installKnowledgeStubs(page)
  await openPage(page)

  const failed = page.locator('.document-item', { hasText: '出院小结.docx' })
  await expect(failed.locator('.document-status')).toContainText('处理失败')
  await expect(failed.locator('.document-failure')).toContainText('解析失败，可以重试')

  await failed.locator('.retry-document').click()
  await expect(failed.locator('.document-status'), '重试后应回到处理中').toContainText('建立索引')
  await expect(failed.locator('.document-status'), '轮询后应变为可用').toContainText('可用', {
    timeout: 15_000,
  })
  await expect(failed.locator('.document-failure')).toHaveCount(0)
})

test('服务端拒绝时显示受控中文，不透传原始报文', async ({ page }) => {
  await installKnowledgeStubs(page, {
    uploadErrorCode: 'PRIVATE_KNOWLEDGE_DOCUMENT_UNSUPPORTED',
  })
  await openPage(page)

  await page.locator('.upload-document').click()
  await page.setInputFiles('input[type="file"]', {
    name: '扫描件.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 e2e'),
  })
  const dialog = page.locator('.private-knowledge-notice-dialog')
  await dialog.locator('.private-knowledge-notice-dialog__agree').click()
  await dialog.getByRole('button', { name: '同意并上传' }).click()

  await expect(dialog).toContainText('这个文件类型暂不支持')
  await expect(page.locator('.private-knowledge-page')).not.toContainText('raw worker trace')
  await expect(page.locator('.document-item', { hasText: '扫描件.pdf' })).toHaveCount(0)
})

test('删除文档要确认：取消保留，确认后消失且数量同步', async ({ page }) => {
  await installKnowledgeStubs(page)
  await openPage(page)

  const row = page.locator('.document-item', { hasText: '体检报告.pdf' })
  await row.locator('.remove-document').click()
  await page.locator('.el-message-box').getByRole('button', { name: '取消' }).click()
  await expect(row, '取消后文档必须还在').toBeVisible()

  await row.locator('.remove-document').click()
  await page.locator('.el-message-box').getByRole('button', { name: '删除' }).click()
  await expect(row).toHaveCount(0)
  await expect(page.locator('.collection-item', { hasText: '我的体检资料' })).toContainText('1 份文档')
})

test('删除知识库会连同文档一起消失', async ({ page }) => {
  await installKnowledgeStubs(page)
  await openPage(page)

  await page.locator('.collection-item', { hasText: '我的体检资料' }).locator('.remove-collection').click()
  const box = page.locator('.el-message-box')
  await expect(box, '删除知识库必须说明会级联删除文档').toContainText('连同其中的全部文档一起删除')
  await box.getByRole('button', { name: '删除' }).click()

  await expect(page.locator('.collection-item', { hasText: '我的体检资料' })).toHaveCount(0)
  await expect(page.locator('.document-name', { hasText: '体检报告.pdf' })).toHaveCount(0)
})

test('达到数量上限时禁用新建并说明原因', async ({ page }) => {
  const many = Array.from({ length: 20 }, (_, index) => collection(`col-${index}`, `库 ${index}`, 0))
  await installKnowledgeStubs(page, { collections: many, documents: new Map() })
  await openPage(page)

  await expect(page.locator('.limit-hint')).toContainText('已达上限（最多 20 个）')
  await expect(page.locator('.create-collection')).toBeDisabled()
})

test('1280px 无横向溢出；375px 按桌面优先约束给出窄屏提示', async ({ page }) => {
  await installKnowledgeStubs(page)

  await page.setViewportSize({ width: 1280, height: 900 })
  await openPage(page)
  const report = await measureOverflow(page)
  const detail = report.offenders
    .map(item => `${item.label}(右边界 ${item.right}px, 宽 ${item.width}px)`)
    .join('；')
  expect(
    report.overflow,
    `1280px 下横向溢出 ${report.overflow}px（scrollWidth=${report.scrollWidth}）越界元素：${detail}`,
  ).toBeLessThanOrEqual(0)

  /*
   * 375px 不要求应用页不溢出：ADR-011 第 2 节把工作区固定成 1000px 的桌面优先版式，
   * 窄屏靠 `.viewport-hint` 明说「需要 1000px」。所以这里断言的是那条既有约定本身，
   * 而不是「无横向溢出」——后者在 375px 下按设计就不可能成立。
   */
  await page.setViewportSize({ width: 375, height: 720 })
  await openPage(page)
  const hint = page.locator('.viewport-hint')
  await expect(hint).toBeVisible()
  await expect(hint).toContainText('1000')
  const workspaceWidth = await page.locator('.workspace').evaluate(
    element => Math.round(element.getBoundingClientRect().width),
  )
  expect(workspaceWidth, '工作区必须保持 1000px 桌面优先约束').toBe(1000)
})

test('知识库内搜索：命中展示文档名/定位/相关度，请求体只有 query+collectionIds+limit', async ({ page }) => {
  const state = await installKnowledgeStubs(page)
  await openPage(page)

  // 搜索区常驻，且明说这一步不进对话（方案 §P2：尚不自动送入模型）。
  await expect(page.locator('.search-scope')).toBeVisible()
  await expect(page.locator('.search-hint')).toContainText('不会自动写进对话')

  await page.locator('.search-input input').fill('血糖')
  await page.locator('.run-search').click()

  await expect(page.locator('.search-hit')).toHaveCount(1)
  await expect(page.locator('.hit-document')).toContainText('体检报告.pdf')
  await expect(page.locator('.hit-source')).toContainText('我的体检资料')
  await expect(page.locator('.hit-similarity')).toContainText('相关度 83%')
  await expect(page.locator('.hit-excerpt')).toContainText('空腹血糖 6.1 mmol/L')

  expect(state.searchBodies.length).toBe(1)
  const body = JSON.parse(state.searchBodies[0]) as Record<string, unknown>
  expect(Object.keys(body).sort()).toEqual(['collectionIds', 'limit', 'query'])
  expect(body.collectionIds).toEqual(['col-1'])
})

test('搜索范围可以加到第二个库，命中按所选范围返回', async ({ page }) => {
  const state = await installKnowledgeStubs(page)
  await openPage(page)

  // 第二个库（用药记录）没有 ready 文档，所以命中仍是一条，但请求范围变成两个库。
  await page.locator('.scope-option input').nth(1).check()
  await page.locator('.search-input input').fill('血糖')
  await page.locator('.run-search').click()
  await expect(page.locator('.search-hit')).toHaveCount(1)

  const body = JSON.parse(state.searchBodies[0]) as { collectionIds: string[] }
  expect([...body.collectionIds].sort()).toEqual(['col-1', 'col-2'])
})

test('搜索被拒时只显示受控中文，不透传原始报文，也不留下旧命中', async ({ page }) => {
  await installKnowledgeStubs(page, { searchErrorCode: 'PRIVATE_KNOWLEDGE_SELECTION_INVALID' })
  await openPage(page)

  await page.locator('.search-input input').fill('血糖')
  await page.locator('.run-search').click()

  await expect(page.locator('.search-error')).toContainText('选择的知识库无效，请重新选择')
  await expect(page.locator('.search-error')).not.toContainText('selection rejected at gateway')
  await expect(page.locator('.search-hit')).toHaveCount(0)
  await expect(page.locator('.search-empty')).toHaveCount(0)
})