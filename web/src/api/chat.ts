import { getToken, api } from './http'

export interface SessionItem {
  session_id: string
  title: string
  updated_at: string
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  text: string
  metadata?: { intent?: string; sources?: { doc_id: string; title: string }[] }
  ts?: string
}

export async function listSessions(): Promise<SessionItem[]> {
  const r = await api.get<{ items: SessionItem[] }>('/chat/sessions')
  return r.data.items
}

export async function getSessionMessages(sessionId: string): Promise<HistoryMessage[]> {
  const r = await api.get<{ items: HistoryMessage[] }>(`/chat/sessions/${sessionId}/messages`)
  return r.data.items
}

export interface StreamHandlers {
  onThinking?: (text: string) => void
  onDelta?: (text: string) => void
  onFinal?: (payload: { text: string; sources: { doc_id: string; title: string }[]; intent: string }) => void
}

/**
 * SSE 流式对话：fetch + ReadableStream 解析（EventSource 不支持 POST）。
 * 对齐 05 §8 事件协议：agent.thinking / message.delta* / message.final。
 */
export async function streamChat(
  query: string,
  spaces: string[],
  handlers: StreamHandlers,
  sessionId?: string,
): Promise<void> {
  const res = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ query, session_id: sessionId, context: { spaces } }),
  })
  if (!res.ok || !res.body) {
    const body = await res.text().catch(() => '')
    throw new Error(`对话请求失败 ${res.status}: ${body}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  const handleBlock = (block: string) => {
    let evt = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) evt = line.slice(7)
      else if (line.startsWith('data: ')) data += line.slice(6)
    }
    if (!data) return
    let payload: any
    try {
      payload = JSON.parse(data)
    } catch {
      return
    }
    if (evt === 'agent.thinking') handlers.onThinking?.(payload.text)
    else if (evt === 'message.delta') handlers.onDelta?.(payload.text)
    else if (evt === 'message.final') handlers.onFinal?.(payload)
  }

  // 注意：SSE 块内既有 event 行又有 data 行，按空行分块
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      if (block.trim()) handleBlock(block)
    }
  }
  if (buf.trim()) handleBlock(buf)
}
