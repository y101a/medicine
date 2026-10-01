import { beforeEach, describe, expect, it, vi } from 'vitest'
import { privateKnowledgeApi, PRIVATE_KNOWLEDGE_NOTICE_VERSION } from './privateKnowledge'
import http from './http'

/**
 * 接口层的契约测试（P1）。
 *
 * 这里**不验证真实链路**（后端即使已落地，本文件也只打桩），只把「前端会发出的请求」钉死：
 * 路径、方法、multipart 字段、以及契约的硬约束（不带 `userId`、不多发字段）。
 * 函数名与签名以 `api/privateKnowledge.ts` 的落地实现为准（Codex 的 P3 接线也用这一份）。
 */
vi.mock('./http', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./http')>()
  return {
    ...actual,
    default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  }
})

const collection = {
  id: 'col-1',
  name: '我的体检资料',
  description: null,
  status: 'active' as const,
  documentCount: 0,
  createdAt: '2026-10-01T00:00:00Z',
  updatedAt: '2026-10-01T00:00:00Z',
}

const document = {
  id: 'doc-1',
  collectionId: 'col-1',
  displayName: '体检报告.pdf',
  kind: 'pdf' as const,
  byteSize: 1024,
  charCount: 0,
  chunkCount: 0,
  parserVersion: 'parser-v1',
  indexVersion: 'index-v1',
  status: 'indexing' as const,
  createdAt: '2026-10-01T00:00:00Z',
  updatedAt: '2026-10-01T00:00:00Z',
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(http.get).mockResolvedValue({ data: { items: [] } })
  vi.mocked(http.post).mockResolvedValue({ data: document })
  vi.mocked(http.patch).mockResolvedValue({ data: collection })
  vi.mocked(http.delete).mockResolvedValue({ data: {} })
})

describe('私人知识库接口层', () => {
  it('列举知识库与文档都走方案 §7 的路径，并展开 items', async () => {
    vi.mocked(http.get).mockResolvedValueOnce({ data: { items: [collection] } })
    await expect(privateKnowledgeApi.collections()).resolves.toEqual([collection])
    expect(http.get).toHaveBeenCalledWith('/private-knowledge/collections')

    vi.mocked(http.get).mockResolvedValueOnce({ data: { items: [document] } })
    await expect(privateKnowledgeApi.documents('col-1')).resolves.toEqual([document])
    expect(http.get).toHaveBeenCalledWith('/private-knowledge/collections/col-1/documents')
  })

  it('新建、改名、删除知识库用各自的路径与动词', async () => {
    await privateKnowledgeApi.createCollection('我的体检资料')
    expect(http.post).toHaveBeenCalledWith('/private-knowledge/collections', {
      name: '我的体检资料',
      description: null,
    })

    await privateKnowledgeApi.updateCollection('col-1', '改名后')
    expect(http.patch).toHaveBeenCalledWith('/private-knowledge/collections/col-1', {
      name: '改名后',
      description: null,
    })

    await privateKnowledgeApi.removeCollection('col-1')
    expect(http.delete).toHaveBeenCalledWith('/private-knowledge/collections/col-1')
  })

  it('单文档状态、重试与删除走文档级路径', async () => {
    await privateKnowledgeApi.getDocument('doc-1')
    expect(http.get).toHaveBeenCalledWith('/private-knowledge/documents/doc-1')

    await privateKnowledgeApi.retryDocument('doc-1')
    expect(http.post).toHaveBeenCalledWith('/private-knowledge/documents/doc-1/retry')

    await privateKnowledgeApi.removeDocument('doc-1')
    expect(http.delete).toHaveBeenCalledWith('/private-knowledge/documents/doc-1')
  })

  it('上传只发文件与说明版本，不发 userId，也不带任何多余字段', async () => {
    const file = new File(['x'], '体检报告.pdf', { type: 'application/pdf' })
    await privateKnowledgeApi.upload('col-1', file)

    expect(http.post).toHaveBeenCalledTimes(1)
    const [url, body, config] = vi.mocked(http.post).mock.calls[0]
    expect(url).toBe('/private-knowledge/collections/col-1/documents')
    expect(config).toEqual({ timeout: 120_000 })

    const form = body as FormData
    expect(form.get('file')).toBe(file)
    expect(form.get('noticeAccepted')).toBe('true')
    expect(form.get('noticeVersion')).toBe(PRIVATE_KNOWLEDGE_NOTICE_VERSION)
    // 契约首行：身份只从认证上下文取，请求体里禁止出现 userId。
    expect(form.get('userId')).toBeNull()
    expect(Array.from(form.keys()).sort()).toEqual(['file', 'noticeAccepted', 'noticeVersion'])
  })

  it('搜索走 POST /search，请求体只有 query / collectionIds / limit，不含 userId（P2）', async () => {
    const hit = {
      referenceNumber: 1,
      collectionId: 'col-1',
      collectionName: '我的体检资料',
      documentId: 'doc-1',
      documentName: '体检报告.pdf',
      locator: '第 1 页 第 2 段',
      excerpt: '空腹血糖 6.1 mmol/L',
      similarity: 0.83,
    }
    vi.mocked(http.post).mockResolvedValueOnce({ data: { items: [hit] } })

    await expect(privateKnowledgeApi.search({
      query: '血糖',
      collectionIds: ['col-1', 'col-2'],
      limit: 5,
    })).resolves.toEqual([hit])

    expect(http.post).toHaveBeenCalledWith('/private-knowledge/search', {
      query: '血糖',
      collectionIds: ['col-1', 'col-2'],
      limit: 5,
    })
    // 契约首行同样适用于检索：身份只从认证上下文取。
    const body = vi.mocked(http.post).mock.calls[0][1] as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual(['collectionIds', 'limit', 'query'])
  })

  it('搜索接口返回的是展开后的 items，页面拿到的就是数组', async () => {
    vi.mocked(http.post).mockResolvedValueOnce({ data: { items: [] } })
    await expect(privateKnowledgeApi.search({ query: '血糖', collectionIds: ['col-1'] }))
      .resolves.toEqual([])
  })
})