import { api } from './http'

export interface MemoryItem {
  memory_id: string
  type: string
  content: string
  tags?: string[]
  importance?: number
  created_at?: string
}

export async function listMemories(kind?: string): Promise<MemoryItem[]> {
  const r = await api.get('/memory', { params: kind ? { kind } : {} })
  return r.data.items
}

export async function searchMemories(q: string): Promise<MemoryItem[]> {
  const r = await api.get('/memory/search', { params: { q } })
  return r.data.items
}

export async function createMemory(
  content: string,
  kind = 'dev_case',
): Promise<{ memory_id: string }> {
  const r = await api.post('/memory', { kind, content })
  return r.data
}

export async function deleteMemory(memoryId: string): Promise<void> {
  await api.delete(`/memory/${memoryId}`)
}
