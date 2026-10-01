export type PrivateKnowledgeDocumentKind = 'pdf' | 'docx' | 'pptx' | 'txt' | 'md'
/**
 * 文档状态：与后端 `backend/app/schemas/private_knowledge.py` 的
 * `PrivateKnowledgeDocumentStatus` 一致（六个值）。前端只读不改写：
 * `deleting` 由删除流程使用，不参与轮询。
 */
export type PrivateKnowledgeDocumentStatus =
  | 'queued'
  | 'parsing'
  | 'indexing'
  | 'ready'
  | 'failed'
  | 'deleting'

export interface PrivateKnowledgeCollection {
  id: string
  name: string
  description?: string | null
  status: 'active'
  documentCount: number
  createdAt: string
  updatedAt: string
}

export interface PrivateKnowledgeDocument {
  id: string
  collectionId: string
  displayName: string
  kind: PrivateKnowledgeDocumentKind
  byteSize: number
  pageCount?: number | null
  charCount: number
  chunkCount: number
  status: PrivateKnowledgeDocumentStatus
  errorCode?: string | null
  /** 解析器与索引版本：后端 `parserVersion` / `indexVersion`（必填），用于解释「为什么需要重试」。 */
  parserVersion: string
  indexVersion: string
  createdAt: string
  updatedAt: string
}

/** 知识库内搜索的一条命中（`POST /private-knowledge/search`，P2）。与后端 `PrivateKnowledgeSearchResult` 一致。 */
export interface PrivateKnowledgeSearchResult {
  referenceNumber: number
  collectionId: string
  collectionName: string
  documentId: string
  documentName: string
  locator: string
  excerpt: string
  similarity: number
}

export interface PrivateKnowledgeSelection {
  id?: string | null
  name: string
  status: 'active' | 'deleted'
}

export interface PrivateKnowledgeCitation {
  referenceNumber: number
  documentId?: string | null
  collectionName?: string | null
  documentName: string
  locator?: string | null
  similarity: number
  status: 'available' | 'deleted'
}
