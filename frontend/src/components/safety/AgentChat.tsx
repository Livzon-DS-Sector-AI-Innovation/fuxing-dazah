'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Button, Spin, Typography, App } from 'antd'
import {
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  DeleteOutlined,
  CheckOutlined,
  CloseOutlined,
  ToolOutlined,
  BookOutlined,
  LinkOutlined,
} from '@ant-design/icons'
import { chatWithAgent, confirmAgentAction } from '@/actions/safety'
import type { AgentChatSource } from '@/types/safety'

const { Text } = Typography

// ── Types ──

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  pendingAction?: {
    id: string
    summary: string
  }
  sources?: AgentChatSource[]
  timestamp: number
}

interface SlashCommand {
  command: string
  description: string
}

// ── Slash Commands ──

const SLASH_COMMANDS: SlashCommand[] = [
  { command: '/help', description: '显示可用指令' },
  { command: '/new', description: '新建会话' },
  { command: '/stop', description: '停止当前生成' },
  { command: '/抄送', description: '将对话结果抄送到飞书' },
]

const HELP_TEXT = `**可用指令**

| 指令 | 说明 |
|------|------|
| \`/help\` | 显示可用指令 |
| \`/new\` | 新建会话，清空对话历史 |
| \`/stop\` | 停止当前正在生成的回复 |
| \`/抄送\` | 将对话结果抄送到飞书（输入 \`/抄送 收件人姓名\`） |

其他问题直接用自然语言输入，Agent 会自动判断意图。`

// ── Markdown render helpers ──

/** Convert minimal Markdown (bold, headings, lists, tables) to HTML for rendering. */
function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/`([^`]+)`/g, '<code style="background:#f0f0f0;padding:1px 4px;border-radius:3px;font-size:13px">$1</code>')
  html = html.replace(/\n### (.+)/g, '\n<h4 style="font-size:14px;margin:8px 0 4px">$1</h4>')
  html = html.replace(/\n## (.+)/g, '\n<h3 style="font-size:15px;margin:8px 0 4px">$1</h3>')
  html = html.replace(/\n- /g, '\n• ')
  html = html.replace(/\n\|(.+)\|/g, (match) => {
    // Simple table row rendering
    const cells = match.split('|').filter(c => c.trim())
    if (cells.every(c => /^[-:\s]+$/.test(c.trim()))) return '' // separator row
    const td = cells.map(c => `<td style="padding:4px 8px;border:1px solid #e5e3df">${c.trim()}</td>`).join('')
    return `<tr>${td}</tr>`
  })
  html = html.replace(/(<tr>.*<\/tr>\n?)+/g, '<table style="border-collapse:collapse;margin:8px 0">$&</table>')
  html = html.replace(/\n/g, '<br/>')
  return html
}

// ═══════════════════════════════════════════════════════════════

export default function AgentChat() {
  const { message } = App.useApp()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [showCommands, setShowCommands] = useState(false)
  const [commandIndex, setCommandIndex] = useState(0)
  const cancelledRef = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<any>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // ── Command helpers ──

  const getFilteredCommands = useCallback((value: string): SlashCommand[] => {
    if (!value.startsWith('/')) return []
    return SLASH_COMMANDS.filter(c => c.command.startsWith(value))
  }, [])

  const executeCommand = useCallback((command: string, args?: string) => {
    setInputValue('')
    setShowCommands(false)

    switch (command) {
      case '/help': {
        const sysMsg: ChatMessage = {
          id: `s-${Date.now()}`,
          role: 'system',
          content: '',
          timestamp: Date.now(),
        }
        const helpMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: HELP_TEXT,
          timestamp: Date.now(),
        }
        setMessages((prev) => [...prev, sysMsg, helpMsg])
        break
      }

      case '/new': {
        setMessages([])
        setSessionId(null)
        message.success('已新建会话')
        break
      }

      case '/stop': {
        if (loading) {
          cancelledRef.current = true
          setLoading(false)
          const stopMsg: ChatMessage = {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content: '⏹ 已停止生成。',
            timestamp: Date.now(),
          }
          setMessages((prev) => [...prev, stopMsg])
          message.info('已停止生成')
        } else {
          message.info('当前没有正在生成的回复')
        }
        break
      }

      case '/抄送': {
        const target = args?.trim() || ''
        if (!target) {
          const promptMsg: ChatMessage = {
            id: `a-${Date.now()}`,
            role: 'assistant',
            content: '📨 **抄送到飞书**\n\n请输入收件人姓名，格式：`/抄送 张三`\n\n当前对话的最后一条回复将被发送到该收件人的飞书私聊。',
            timestamp: Date.now(),
          }
          setMessages((prev) => [...prev, promptMsg])
          return
        }
        // Find the last assistant message
        const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
        if (!lastAssistant) {
          message.warning('当前对话没有可抄送的内容')
          return
        }
        // Format and copy to clipboard (backend forward endpoint pending)
        const summary = `[安全管理AI助手 - 对话抄送]\n收件人: ${target}\n---\n${lastAssistant.content}`
        navigator.clipboard.writeText(summary).then(() => {
          message.success(`已复制对话内容到剪贴板，请粘贴到飞书发送给 ${target}`)
        }).catch(() => {
          message.info('抄送内容已生成，请手动复制发送')
        })
        const fwdMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: `📨 已准备抄送内容（收件人：**${target}**）\n\n内容已复制到剪贴板，请打开飞书粘贴发送。\n\n> ${lastAssistant.content.slice(0, 200)}${lastAssistant.content.length > 200 ? '…' : ''}`,
          timestamp: Date.now(),
        }
        setMessages((prev) => [...prev, fwdMsg])
        break
      }
    }
  }, [loading, messages, message])

  // ── Input handlers ──

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value
    setInputValue(value)

    const filtered = getFilteredCommands(value)
    if (filtered.length > 0 && !value.includes(' ') && value.length <= 6) {
      setShowCommands(true)
      setCommandIndex(0)
    } else {
      setShowCommands(false)
    }
  }, [getFilteredCommands])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (showCommands) {
      const filtered = getFilteredCommands(inputValue)
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setCommandIndex((prev) => (prev + 1) % filtered.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setCommandIndex((prev) => (prev - 1 + filtered.length) % filtered.length)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        if (filtered[commandIndex]) {
          executeCommand(filtered[commandIndex].command)
        }
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setShowCommands(false)
        return
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [showCommands, inputValue, commandIndex, getFilteredCommands, executeCommand])

  // ── Send ──

  const handleSend = useCallback(async (text?: string) => {
    const query = (text || inputValue).trim()
    if (!query || loading) return

    // Check for slash commands starting with a space (e.g. "/抄送 张三")
    if (query.startsWith('/')) {
      const spaceIdx = query.indexOf(' ')
      const cmd = spaceIdx > 0 ? query.slice(0, spaceIdx) : query
      const args = spaceIdx > 0 ? query.slice(spaceIdx + 1) : ''
      const validCmd = SLASH_COMMANDS.find(c => c.command === cmd)
      if (validCmd) {
        // Show user message first
        const userMsg: ChatMessage = {
          id: `u-${Date.now()}`,
          role: 'user',
          content: query,
          timestamp: Date.now(),
        }
        setMessages((prev) => [...prev, userMsg])
        executeCommand(cmd, args)
        setInputValue('')
        setShowCommands(false)
        return
      }
    }

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: Date.now(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInputValue('')
    setShowCommands(false)
    setLoading(true)
    cancelledRef.current = false

    try {
      const res = await chatWithAgent(query, sessionId ?? undefined)

      // Check if cancelled
      if (cancelledRef.current) return

      if (res.code === 200 && res.data) {
        if (!sessionId) setSessionId(res.data.session_id)

        const pending = res.data.pending_action_id && res.data.pending_action
          ? { id: res.data.pending_action_id, summary: res.data.pending_action.summary }
          : undefined

        const aiMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: res.data.answer,
          pendingAction: pending,
          sources: res.data.sources || [],
          timestamp: Date.now(),
        }
        setMessages((prev) => [...prev, aiMsg])
      } else {
        message.error(res.message || '请求失败')
      }
    } catch (err) {
      if (cancelledRef.current) return
      message.error(`网络请求失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      if (!cancelledRef.current) {
        setLoading(false)
      }
    }
  }, [inputValue, loading, sessionId, message, executeCommand])

  const handleConfirm = useCallback(async (actionId: string, approved: boolean) => {
    setConfirmingId(actionId)
    try {
      const res = await confirmAgentAction(actionId, approved)
      if (res.code === 200 && res.data) {
        const resultMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: res.data.answer,
          timestamp: Date.now(),
        }
        setMessages((prev) => [...prev, resultMsg])
        message.success(approved ? '操作已执行' : '操作已取消')
      } else {
        message.error(res.message || '操作失败')
      }
    } catch (err) {
      message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setConfirmingId(null)
    }
  }, [])

  const handleClear = () => {
    setMessages([])
    setSessionId(null)
  }

  // ── 引用来源（RAG sources） ──
  const renderSources = (sources: AgentChatSource[]) => {
    if (!sources || sources.length === 0) return null
    return (
      <div
        style={{
          marginTop: 10,
          borderTop: '1px dashed var(--color-hairline, #e5e3df)',
          paddingTop: 8,
        }}
      >
        <div
          style={{
            fontSize: 12,
            color: 'var(--color-stone, #a4a097)',
            marginBottom: 6,
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <BookOutlined style={{ fontSize: 12 }} />
          引用来源（{sources.length}）
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {sources.map((s, i) => (
            <div
              key={i}
              style={{
                padding: '8px 10px',
                background: 'var(--color-surface-soft, #fafaf9)',
                border: '1px solid var(--color-hairline-soft, #ede9e4)',
                borderRadius: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: 'var(--color-ink, #1a1a1a)',
                    lineHeight: 1.4,
                    minWidth: 0,
                  }}
                >
                  {s.doc_title}
                </span>
                {s.feishu_url ? (
                  <a
                    href={s.feishu_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      fontSize: 12,
                      color: 'var(--color-primary, #5645d4)',
                      whiteSpace: 'nowrap',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 3,
                      flexShrink: 0,
                    }}
                  >
                    <LinkOutlined style={{ fontSize: 11 }} />
                    查看原文
                  </a>
                ) : null}
              </div>

              {(s.article_ref || s.doc_category) && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                  {s.article_ref && (
                    <span
                      style={{
                        display: 'inline-block',
                        padding: '0 6px',
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--color-primary, #5645d4)',
                        background: '#e6e0f5',
                        lineHeight: '18px',
                      }}
                    >
                      {s.article_ref}
                    </span>
                  )}
                  {s.doc_category && (
                    <span
                      style={{
                        display: 'inline-block',
                        padding: '0 6px',
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--color-slate, #5d5b54)',
                        background: 'var(--color-surface, #f0eeec)',
                        lineHeight: '18px',
                      }}
                    >
                      {s.doc_category}
                    </span>
                  )}
                </div>
              )}

              {s.chunk_text && (
                <div
                  style={{
                    marginTop: 4,
                    fontSize: 12,
                    lineHeight: 1.6,
                    color: 'var(--color-charcoal, #37352f)',
                    display: '-webkit-box',
                    WebkitLineClamp: 3,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                    wordBreak: 'break-word',
                  }}
                >
                  {s.chunk_text}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  // ── Render ──

  const filteredCommands = showCommands ? getFilteredCommands(inputValue) : []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 112px)' }}>
      {/* ── Header ── */}
      <div
        style={{
          padding: '16px 24px',
          borderBottom: '1px solid var(--color-hairline, #e5e3df)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 600, color: 'var(--color-charcoal, #1a1a1a)', margin: 0, lineHeight: 1.3 }}>
            <ToolOutlined style={{ marginRight: 8, color: 'var(--color-primary, #5645d4)' }} />
            安全管理AI助手
          </h2>
          <p style={{ fontSize: 13, color: 'var(--color-stone, #787671)', margin: '2px 0 0' }}>
            输入 <code style={{ background: '#f0f0f0', padding: '1px 4px', borderRadius: 3 }}>/</code> 查看指令 · 写操作需确认后执行
          </p>
        </div>
        {messages.length > 0 && (
          <Button icon={<DeleteOutlined />} onClick={handleClear} size="small">清空对话</Button>
        )}
      </div>

      {/* ── Messages ── */}
      <div
        style={{
          flex: 1, overflowY: 'auto', padding: '20px 24px',
          background: 'var(--color-surface, #f7f6f4)',
        }}
      >
        {messages.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 24 }}>
            <div style={{ textAlign: 'center' }}>
              <RobotOutlined style={{ fontSize: 48, color: 'var(--color-primary, #5645d4)', marginBottom: 16 }} />
              <h3 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
                安全助手
              </h3>
              <p style={{ fontSize: 14, color: '#787671', marginTop: 8, maxWidth: 480 }}>
                专注于安全法律法规、标准规范和管理制度的检索。输入您的问题，我会从知识库中查找相关法规并给出引用回答。
              </p>
              <p style={{ fontSize: 13, color: '#a4a097', marginTop: 6 }}>
                输入 <code style={{ background: '#f0f0f0', padding: '1px 5px', borderRadius: 3 }}>/</code> 查看快捷指令 · 切换话题前建议用 <code style={{ background: '#f0f0f0', padding: '1px 5px', borderRadius: 3 }}>/new</code> 清空上下文
              </p>
            </div>
            {/* Suggestion chips */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', maxWidth: 600 }}>
              {[
                '防爆电气设备安装有哪些标准要求',
                '危险化学品储存安全管理规定',
                '受限空间作业安全规范',
              ].map((s) => (
                <span
                  key={s}
                  onClick={() => handleSend(s)}
                  style={{
                    cursor: 'pointer', padding: '6px 14px', fontSize: 13, borderRadius: 20,
                    border: '1px solid #e5e3df', background: '#fff', transition: 'all 0.15s',
                  }}
                  onMouseEnter={(e) => {
                    (e.target as HTMLElement).style.borderColor = 'var(--color-primary, #5645d4)'
                    ;(e.target as HTMLElement).style.color = 'var(--color-primary, #5645d4)'
                  }}
                  onMouseLeave={(e) => {
                    ;(e.target as HTMLElement).style.borderColor = '#e5e3df'
                    ;(e.target as HTMLElement).style.color = ''
                  }}
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ maxWidth: 800, margin: '0 auto' }}>
            {messages.map((msg) => (
              <div
                key={msg.id}
                style={{
                  marginBottom: 20,
                  display: 'flex', flexDirection: 'column',
                  alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                }}
              >
                {/* Role label */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, fontSize: 12, color: '#787671' }}>
                  {msg.role === 'user' ? (
                    <><span>你</span><UserOutlined /></>
                  ) : msg.role === 'system' ? (
                    <><span>系统</span></>
                  ) : (
                    <><RobotOutlined style={{ color: 'var(--color-primary, #5645d4)' }} /><span>安全助手</span></>
                  )}
                </div>

                {/* Bubble — skip for system messages */}
                {msg.role !== 'system' && (
                  <div
                    style={{
                      maxWidth: '90%', padding: '12px 16px', borderRadius: 12,
                      background: msg.role === 'user' ? 'var(--color-primary, #5645d4)' : '#ffffff',
                      color: msg.role === 'user' ? '#ffffff' : '#1a1a1a',
                      border: msg.role === 'user' ? 'none' : '1px solid #e5e3df',
                      lineHeight: 1.7, fontSize: 14,
                    }}
                  >
                    {msg.role === 'user' ? (
                      <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{msg.content}</div>
                    ) : (
                      <div
                        style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                      />
                    )}

                    {/* 引用来源（RAG 检索到的法规） */}
                    {msg.sources && msg.sources.length > 0 && renderSources(msg.sources)}

                    {/* Pending action card */}
                    {msg.pendingAction && (
                      <div
                        style={{
                          marginTop: 12, padding: '10px 12px',
                          background: '#f7f6f4', borderRadius: 8,
                          border: '1px solid #e5e3df',
                        }}
                      >
                        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                          ⚠️ 该操作需要您确认后才能执行
                        </Text>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <Button
                            type="primary"
                            size="small"
                            icon={<CheckOutlined />}
                            loading={confirmingId === msg.pendingAction.id}
                            onClick={() => handleConfirm(msg.pendingAction!.id, true)}
                            style={{ borderRadius: 6 }}
                          >
                            确认执行
                          </Button>
                          <Button
                            size="small"
                            danger
                            icon={<CloseOutlined />}
                            disabled={confirmingId === msg.pendingAction.id}
                            onClick={() => handleConfirm(msg.pendingAction!.id, false)}
                            style={{ borderRadius: 6 }}
                          >
                            取消
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
                <RobotOutlined style={{ color: 'var(--color-primary, #5645d4)' }} />
                <Spin size="small" />
                <Text type="secondary" style={{ fontSize: 13 }}>正在处理您的请求...</Text>
                <Button
                  type="link"
                  size="small"
                  onClick={() => executeCommand('/stop')}
                  style={{ fontSize: 12, padding: 0 }}
                >
                  停止
                </Button>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* ── Input ── */}
      <div
        style={{
          padding: '12px 24px 16px',
          borderTop: '1px solid var(--color-hairline, #e5e3df)',
          background: '#ffffff', flexShrink: 0,
          position: 'relative',
        }}
      >
        {/* ── Command dropdown ── */}
        {showCommands && filteredCommands.length > 0 && (
          <div
            style={{
              position: 'absolute', bottom: '100%', left: 24, right: 24, maxWidth: 800, margin: '0 auto',
              background: '#fff', border: '1px solid #e5e3df', borderRadius: 8,
              boxShadow: '0 4px 16px rgba(0,0,0,0.1)', zIndex: 100, overflow: 'hidden',
              marginBottom: 8,
            }}
          >
            {filteredCommands.map((cmd, idx) => (
              <div
                key={cmd.command}
                onClick={() => executeCommand(cmd.command)}
                onMouseEnter={() => setCommandIndex(idx)}
                style={{
                  padding: '10px 16px',
                  cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 12,
                  background: idx === commandIndex ? 'var(--color-surface, #f7f6f4)' : 'transparent',
                  borderBottom: idx < filteredCommands.length - 1 ? '1px solid #f0f0f0' : 'none',
                }}
              >
                <code style={{
                  background: 'var(--color-primary, #5645d4)', color: '#fff',
                  padding: '2px 8px', borderRadius: 4, fontSize: 13, fontWeight: 600,
                }}>
                  {cmd.command}
                </code>
                <span style={{ fontSize: 13, color: '#787671' }}>{cmd.description}</span>
              </div>
            ))}
          </div>
        )}

        <div style={{ maxWidth: 800, margin: '0 auto', display: 'flex', gap: 10 }}>
          <Input.TextArea
            ref={inputRef}
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="输入问题，或输入 / 查看指令…"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            style={{ flex: 1, borderRadius: 8 }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => handleSend()}
            loading={loading}
            disabled={!inputValue.trim()}
            style={{ borderRadius: 8, height: 'auto', minWidth: 48 }}
          >
            发送
          </Button>
        </div>
        <p style={{ fontSize: 11, color: '#a4a097', textAlign: 'center', margin: '6px 0 0' }}>
          输入 <code>/</code> 使用快捷指令 · Enter 发送 · Shift + Enter 换行
        </p>
      </div>
    </div>
  )
}
