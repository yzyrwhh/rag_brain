import { api } from './http'

export interface Space {
  space_id: string
  name: string
  description?: string
  type?: string
}

export interface Document {
  doc_id: string
  title: string
  file_name: string
  status: string
  chunk_count: number
  tags?: string[]
}

export interface SearchHit {
  chunk_id: string
  doc_id: string
  text: string
  score: number
  source: string
}

export async function listSpaces(): Promise<Space[]> {
  const r = await api.get<{ items: Space[] }>('/knowledge/spaces')
  return r.data.items
}

export async function createSpace(name: string, description = ''): Promise<Space> {
  const r = await api.post<Space>('/knowledge/spaces', { name, description })
  return r.data
}

export async function listDocuments(spaceId: string): Promise<Document[]> {
  const r = await api.get<{ items: Document[] }>(`/knowledge/spaces/${spaceId}/documents`)
  return r.data.items
}

export async function getDocument(docId: string): Promise<Document> {
  const r = await api.get<Document>(`/knowledge/documents/${docId}`)
  return r.data
}

export async function uploadDocument(
  spaceId: string,
  file: File,
  domain = 'general',
): Promise<{ doc_id: string; task_id: string }> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('domain', domain)
  const r = await api.post(`/knowledge/spaces/${spaceId}/documents`, fd)
  return r.data
}

export async function searchKnowledge(
  query: string,
  spaceIds: string[],
  topK = 5,
): Promise<{ results: SearchHit[]; elapsed_ms: number }> {
  const r = await api.post('/knowledge/search', { query, space_ids: spaceIds, top_k: topK })
  return r.data
}

export async function askKnowledge(
  query: string,
  spaceIds: string[],
): Promise<{ answer: string; sources: { doc_id: string; title: string }[] }> {
  const r = await api.post('/knowledge/ask', { query, space_ids: spaceIds, top_k: 5 })
  return r.data
}
