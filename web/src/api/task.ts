import { getToken } from './http'

export interface TaskEvent {
  type: string
  payload: any
}

/** 通用 SSE 解析（fetch + ReadableStream；EventSource 不支持鉴权头与游标参数） */
async function readSSE(res: Response, onEvent: (type: string, payload: any) => void): Promise<void> {
  if (!res.ok || !res.body) throw new Error(`事件订阅失败 ${res.status}`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  const handle = (block: string) => {
    let evt = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) evt = line.slice(7)
      else if (line.startsWith('data: ')) data += line.slice(6)
    }
    if (!data) return
    try {
      onEvent(evt, JSON.parse(data))
    } catch {
      /* 忽略坏帧 */
    }
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      if (block.trim()) handle(block)
    }
  }
  if (buf.trim()) handle(buf)
}

/** 订阅任务事件流（05 §8 契约：node.start/end、agent.thinking、tool.call/result、task.completed/failed） */
export async function subscribeTaskEvents(
  taskId: string,
  onEvent: (ev: TaskEvent) => void,
): Promise<void> {
  const res = await fetch(`/api/v1/tasks/${taskId}/events?after_seq=0`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  await readSSE(res, (type, payload) => onEvent({ type, payload }))
}
