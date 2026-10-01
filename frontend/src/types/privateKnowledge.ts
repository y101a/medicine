export type PrivateKnowledgeDocumentKind = 'pdf' | 'docx' | 'pptx' | 'txt' | 'md'
export type PrivateKnowledgeDocumentStatus = 'indexing' | 'ready' | 'failed'

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
  createdAt: string
  updatedAt: string
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
