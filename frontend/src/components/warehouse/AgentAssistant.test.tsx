import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentAssistant, parseSseBlock } from './AgentAssistant'

describe('parseSseBlock', () => {
  it('解析单事件', () => {
    const parsed = parseSseBlock('event: message\ndata: {"text": "你好", "seq": 3}\n\n')
    expect(parsed?.event).toBe('message')
    expect(parsed?.data).toEqual({ text: '你好', seq: 3 })
  })

  it('无 data 返回 null', () => {
    expect(parseSseBlock('event: ping\n\n')).toBeNull()
  })

  it('非法 JSON 返回 null', () => {
    expect(parseSseBlock('event: message\ndata: not-json\n\n')).toBeNull()
  })
})

function sseResponse(events: Array<[string, Record<string, unknown>]>): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      for (const [event, data] of events) {
        controller.enqueue(
          encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
        )
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

describe('AgentAssistant', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('默认渲染悬浮按钮，点击打开聊窗', async () => {
    const user = userEvent.setup()
    render(<AgentAssistant />)

    await user.click(screen.getByRole('button', { name: '打开仓储助手' }))
    expect(screen.getByText('仓储助手')).toBeInTheDocument()
    expect(screen.getByText(/你好，我是仓储助手/)).toBeInTheDocument()
  })

  it('发送消息后渲染流式回复', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        ['accepted', { open_id: 'web:1' }],
        ['stage', { label: '正在处理' }],
        ['message', { text: '库存 12 kg' }],
        ['finished', { duration_ms: 100 }],
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    render(<AgentAssistant />)
    await user.click(screen.getByRole('button', { name: '打开仓储助手' }))
    await user.type(screen.getByPlaceholderText('输入问题，回车发送'), '查库存')
    await user.click(screen.getByRole('button', { name: /发\s*送/ }))

    await waitFor(() => expect(screen.getByText('库存 12 kg')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/warehouse/agent/chat/stream',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('error 事件显示错误提示', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        ['accepted', {}],
        ['error', { message: '助手处理失败' }],
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const user = userEvent.setup()
    render(<AgentAssistant />)
    await user.click(screen.getByRole('button', { name: '打开仓储助手' }))
    await user.type(screen.getByPlaceholderText('输入问题，回车发送'), '查库存')
    await user.click(screen.getByRole('button', { name: /发\s*送/ }))

    expect(await screen.findByText('助手处理失败', {}, { timeout: 3000 })).toBeInTheDocument()
  })
})
