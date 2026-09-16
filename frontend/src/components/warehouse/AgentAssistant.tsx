'use client'

import { useRef, useState } from 'react'
import { Alert, Button, Input, Space, Typography } from 'antd'
import { RobotOutlined, SendOutlined } from '@ant-design/icons'

/** 单条 SSE 事件解析：block = "event: xxx\ndata: {...}\n\n" */
export function parseSseBlock(block: string): { event: string; data: Record<string, unknown> } | null {
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

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

const WELCOME = '你好，我是仓储助手。可以问我库存、出入库、异常等问题，也可以让我帮你登记。'

export function AgentAssistant() {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [stage, setStage] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const send = async () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    setError(null)
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setStreaming(true)
    setStage('正在连接助手…')
    let answer = ''

    try {
      const resp = await fetch('/api/v1/warehouse/agent/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })
      if (!resp.ok || !resp.body) {
        const body = (await resp.json().catch(() => null)) as { message?: string } | null
        throw new Error(body?.message ?? `助手服务异常（${resp.status}）`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      setMessages(prev => [...prev, { role: 'assistant', content: '' }])

      const updateLast = (content: string) => {
        setMessages(prev => {
          const next = [...prev]
          next[next.length - 1] = { role: 'assistant', content }
          return next
        })
      }

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() ?? ''
        for (const block of blocks) {
          const parsed = parseSseBlock(block)
          if (!parsed) continue
          if (parsed.event === 'stage') {
            setStage(String(parsed.data.label ?? '正在处理'))
          } else if (parsed.event === 'message') {
            setStage(null)
            answer = String(parsed.data.text ?? '')
            updateLast(answer)
          } else if (parsed.event === 'error') {
            setStage(null)
            setError(String(parsed.data.message ?? '助手处理失败'))
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '助手连接失败')
    } finally {
      setStreaming(false)
      setStage(null)
      // 保留已设置的真实错误；无错误且无内容时给兜底文案
      setError(prev => prev ?? (answer ? null : '助手没有返回内容'))
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }

  if (!open) {
    return (
      <Button
        type="primary"
        shape="circle"
        size="large"
        icon={<RobotOutlined />}
        style={{ position: 'fixed', right: 24, bottom: 24, zIndex: 1000, width: 56, height: 56 }}
        onClick={() => setOpen(true)}
        aria-label="打开仓储助手"
      />
    )
  }

  return (
    <div
      style={{
        position: 'fixed',
        right: 24,
        bottom: 24,
        width: 420,
        height: 620,
        background: 'var(--ant-color-bg-container, #fff)',
        borderRadius: 12,
        boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--ant-color-border, #eee)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <Typography.Text strong>仓储助手</Typography.Text>
        <Button size="small" type="text" onClick={() => setOpen(false)}>
          收起
        </Button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
        <Typography.Paragraph type="secondary">{WELCOME}</Typography.Paragraph>
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              margin: '8px 0',
              textAlign: m.role === 'user' ? 'right' : 'left',
            }}
          >
            <span
              style={{
                display: 'inline-block',
                padding: '6px 10px',
                borderRadius: 8,
                background:
                  m.role === 'user'
                    ? 'var(--ant-color-primary-bg, #f0f0ff)'
                    : 'var(--ant-color-fill-tertiary, #f5f5f5)',
                maxWidth: '90%',
                whiteSpace: 'pre-wrap',
                textAlign: 'left',
              }}
            >
              {m.content}
            </span>
          </div>
        ))}
        {stage && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {stage}
          </Typography.Text>
        )}
        {error && (
          <Alert type="error" showIcon message={error} style={{ marginTop: 8 }} />
        )}
        <div ref={bottomRef} />
      </div>

      <div style={{ padding: 12, borderTop: '1px solid var(--ant-color-border, #eee)' }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="输入问题，回车发送"
            value={input}
            disabled={streaming}
            onChange={e => setInput(e.target.value)}
            onPressEnter={send}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={streaming}
            onClick={send}
          >
            发送
          </Button>
        </Space.Compact>
      </div>
    </div>
  )
}
