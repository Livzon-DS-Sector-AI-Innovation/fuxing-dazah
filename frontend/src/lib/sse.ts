/**
 * SSE 事件块解析（流式对话共用）。
 *
 * 单条事件块形如 `event: xxx\ndata: {...}\n\n`；与仓储 AgentAssistant 的
 * parseSseBlock 同款实现，抽到共享 lib 供安全/仓储两侧复用。
 */
export function parseSseBlock(
  block: string,
): { event: string; data: Record<string, unknown> } | null {
  let event = 'message'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  if (!data) return null
  try {
    return { event, data: JSON.parse(data) as Record<string, unknown> }
  } catch {
    return null
  }
}

/** 逐块消费 SSE 流：按 `\n\n` 切块并解析，解析失败静默跳过。 */
export async function consumeSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const parsed = parseSseBlock(block)
      if (parsed) onEvent(parsed.event, parsed.data)
    }
  }
  const tail = parseSseBlock(buffer)
  if (tail) onEvent(tail.event, tail.data)
}
