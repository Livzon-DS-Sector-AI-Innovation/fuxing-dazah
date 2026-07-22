'use client'

import { useState, useRef, useEffect } from 'react'
import { Input, Button, Spin, Typography, Tag } from 'antd'
import {
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  FileTextOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { queryKnowledgeChat } from '@/actions/safety'
import type { InfoQuerySource } from '@/types/safety'

const { Text } = Typography

// ── Suggested starter questions ──
const SUGGESTIONS = [
  '电气安全相关的法律法规有哪些？',
  '动火作业的具体条款是什么？',
  '防爆区域的电气设备安装有什么要求？',
  '受限空间作业需要满足哪些安全条件？',
  '危险化学品的储存禁忌有哪些规定？',
]

// ── Types ──

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: InfoQuerySource[]
  timestamp: number
}

// ── Helpers ──

/** Standard number patterns found in Chinese safety regulations. */
const STD_NO_PATTERN = /(?:GB(?:\/T|Z)?|AQ(?:\/T)?|HG(?:\/T)?|SY(?:\/T)?|SH(?:\/T)?|DB\d{2}(?:\/T)?)\s*[\d.]+-\d{2,4}/gi

/**
 * Check whether a document title is referenced in the AI answer text.
 */
function isTitleReferencedInAnswer(title: string, answer: string): boolean {
  // (a) Standard numbers: "GB 3836.1-2010", "HG 20571-2014", etc.
  const stdMatches = title.match(STD_NO_PATTERN)
  if (stdMatches) {
    for (const std of stdMatches) {
      if (answer.includes(std)) return true
    }
  }
  // (b) 《Title》 in source → search in answer
  const bookRe = /《([^》]+)》/g
  let bm: RegExpExecArray | null
  while ((bm = bookRe.exec(title)) !== null) {
    if (answer.includes(bm[1])) return true
  }
  // (c) 《Title》 in answer → search in source (reverse)
  let am: RegExpExecArray | null
  while ((am = bookRe.exec(answer)) !== null) {
    if (title.includes(am[1])) return true
  }
  // (d) Significant words from title (≥5 chars, not generic)
  const genericWords = new Set([
    '管理制度', '安全操作规程', '安全规定', '管理办法', '应急预案',
    '标准规范', '安全生产', '管理规定', '技术规范', '操作规程',
  ])
  const words = title.split(/[\s《》—\-、，。·「」]+/).filter(
    (w) => w.length >= 5 && !genericWords.has(w)
  )
  for (const word of words) {
    if (answer.includes(word)) return true
  }
  return false
}

/**
 * Find which sources are cited in the answer, deduped and ordered by
 * first mention.  Only title matching is used — AI marker numbers are
 * discarded because the model hallucinates them.
 */
function getCitedSources(answer: string, sources: InfoQuerySource[]): InfoQuerySource[] {
  // 1. Deduplicate by trimmed title, preferring entries with feishu_url
  const seen = new Set<string>()
  const unique: InfoQuerySource[] = []
  for (const s of sources) {
    const key = s.doc_title.trim()
    if (!seen.has(key)) {
      seen.add(key)
      unique.push(s)
    } else if (s.feishu_url) {
      const idx = unique.findIndex((u) => u.doc_title.trim() === key && !u.feishu_url)
      if (idx >= 0) unique[idx] = s
    }
  }

  // 2. Find which unique sources are actually referenced in the answer
  const cited = unique.filter((s) => isTitleReferencedInAnswer(s.doc_title, answer))

  // 3. Sort by first mention position in the answer text
  cited.sort((a, b) => {
    const posA = answer.indexOf(a.doc_title.replace(/[《》]/g, '').substring(0, 8))
    const posB = answer.indexOf(b.doc_title.replace(/[《》]/g, '').substring(0, 8))
    // If not found (shouldn't happen), put at end
    if (posA === -1 && posB === -1) return 0
    if (posA === -1) return 1
    if (posB === -1) return -1
    return posA - posB
  })

  return cited
}

const BADGE_STYLE = 'display:inline-block;cursor:pointer;color:var(--color-primary,#5645d4);font-weight:700;font-size:11px;line-height:1;padding:0 2px;border-radius:2px;transition:background .15s'
const BADGE_HOVER = "onmouseenter=\"this.style.background='#f0eeec'\" onmouseleave=\"this.style.background='transparent'\""

/**
 * Render AI answer HTML with clickable inline citation badges.
 *
 * 1. Scans for 《Title》 mentions and injects sequential [N] badges.
 * 2. Replaces any pre-existing [N] / 【N】 markers (AI hallucinated)
 *    with badges pointing to the correct display index.
 */
function renderAnswerWithCitations(
  answer: string,
  citedSources: InfoQuerySource[],
): string {
  // Build lookup: doc_title substring → display index
  const titleToIdx: Record<string, number> = {}
  citedSources.forEach((s, i) => {
    // Store the first 10 chars of title as key (enough to disambiguate)
    const key = s.doc_title.substring(0, 10)
    titleToIdx[key] = i + 1
  })

  // Escape HTML
  let html = answer
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Formatting
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\n## (.+)/g, '\n<h3 style="font-size:15px;margin:8px 0 4px">$1</h3>')
  html = html.replace(/\n- /g, '\n• ')

  const badge = (idx: number) =>
    `<sup class="cite-badge" data-cite="${idx}" style="${BADGE_STYLE}" ${BADGE_HOVER}>[${idx}]</sup>`

  // ── Step 1: Strip AI-original [N] / 【N】 markers FIRST ──
  // Must run BEFORE injection, otherwise the regex would also strip
  // the [N] text from inside the <sup> badges we just injected.
  html = html.replace(/\[\d+\]/g, '').replace(/【\d+】/g, '')

  // ── Step 2: Inject sequential [N] badges after 《Title》 mentions ──
  html = html.replace(/《([^》]+)》(?!\s*[<\[])/g, (_full: string, title: string) => {
    for (let i = 0; i < citedSources.length; i++) {
      const s = citedSources[i]
      if (s.doc_title.includes(title) || title.includes(s.doc_title)) {
        return `《${title}》 ${badge(i + 1)}`
      }
    }
    return _full
  })

  return html
}

// ═══════════════════════════════════════════════════════════════

export default function InfoQueryChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<any>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSend = async (text?: string) => {
    const query = (text || inputValue).trim()
    if (!query || loading) return

    // Add user message
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: Date.now(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInputValue('')
    setLoading(true)

    try {
      // Build history from previous messages
      const history: { role: string; content: string }[] = []
      for (const msg of messages.slice(-6)) {
        // last 3 turns
        history.push({ role: msg.role, content: msg.content })
      }

      const res = await queryKnowledgeChat(query, history)

      if (res.code === 200 && res.data) {
        const aiMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: res.data.answer,
          sources: res.data.sources,
          timestamp: Date.now(),
        }
        setMessages((prev) => [...prev, aiMsg])
      } else {
        const errMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: `抱歉，查询失败：${res.message || '未知错误'}`,
          timestamp: Date.now(),
        }
        setMessages((prev) => [...prev, errMsg])
      }
    } catch (err) {
      const errMsg: ChatMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: `网络请求失败：${err instanceof Error ? err.message : String(err)}`,
        timestamp: Date.now(),
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setLoading(false)
    }
  }

  const handleClear = () => {
    setMessages([])
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // ── Render ──

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 112px)' }}>
      {/* ── Header ── */}
      <div
        style={{
          padding: '16px 24px',
          borderBottom: '1px solid var(--color-hairline, #e5e3df)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <div>
          <h2
            style={{
              fontSize: 20,
              fontWeight: 600,
              color: 'var(--color-charcoal, #1a1a1a)',
              margin: 0,
              lineHeight: 1.3,
            }}
          >
            <RobotOutlined style={{ marginRight: 8, color: 'var(--color-primary, #5645d4)' }} />
            安全信息查询
          </h2>
          <p
            style={{
              fontSize: 13,
              color: 'var(--color-stone, #787671)',
              margin: '2px 0 0',
            }}
          >
            基于知识库的 AI 智能问答 — 支持法规条款检索与原文引用
          </p>
        </div>
        {messages.length > 0 && (
          <Button icon={<DeleteOutlined />} onClick={handleClear} size="small">
            清空对话
          </Button>
        )}
      </div>

      {/* ── Messages Area ── */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px 24px',
          background: 'var(--color-surface, #f7f6f4)',
        }}
      >
        {messages.length === 0 ? (
          /* Welcome state */
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              gap: 24,
            }}
          >
            <div style={{ textAlign: 'center' }}>
              <RobotOutlined
                style={{ fontSize: 48, color: 'var(--color-primary, #5645d4)', marginBottom: 16 }}
              />
              <h3 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
                安全法规智能助手
              </h3>
              <p style={{ fontSize: 14, color: '#787671', marginTop: 8, maxWidth: 480 }}>
                您可以询问任何安全生产相关的法规问题，AI 将从知识库中检索相关条款并给出带引用的回答。
              </p>
            </div>

            {/* Suggestion chips */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', maxWidth: 600 }}>
              {SUGGESTIONS.map((s) => (
                <Tag
                  key={s}
                  style={{
                    cursor: 'pointer',
                    padding: '6px 14px',
                    fontSize: 13,
                    borderRadius: 20,
                    border: '1px solid #e5e3df',
                    background: '#fff',
                    transition: 'all 0.15s',
                  }}
                  onClick={() => handleSend(s)}
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
                </Tag>
              ))}
            </div>
          </div>
        ) : (
          /* Message list */
          <div style={{ maxWidth: 800, margin: '0 auto' }}>
            {messages.map((msg) => (
              <div
                key={msg.id}
                style={{
                  marginBottom: 20,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                }}
              >
                {/* Role indicator */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    marginBottom: 4,
                    fontSize: 12,
                    color: '#787671',
                  }}
                >
                  {msg.role === 'user' ? (
                    <>
                      <span>你</span>
                      <UserOutlined />
                    </>
                  ) : (
                    <>
                      <RobotOutlined style={{ color: 'var(--color-primary, #5645d4)' }} />
                      <span>AI 助手</span>
                    </>
                  )}
                </div>

                {/* Message bubble */}
                <div
                  style={{
                    maxWidth: '90%',
                    padding: '12px 16px',
                    borderRadius: 12,
                    background: msg.role === 'user' ? 'var(--color-primary, #5645d4)' : '#ffffff',
                    color: msg.role === 'user' ? '#ffffff' : '#1a1a1a',
                    border: msg.role === 'user' ? 'none' : '1px solid #e5e3df',
                    lineHeight: 1.7,
                    fontSize: 14,
                  }}
                >
                  {/* Render AI answer with inline citation badges */}
                  {msg.role === 'user' ? (
                    <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {msg.content}
                    </div>
                  ) : (
                    (() => {
                      const sources = msg.sources || []
                      const cited = getCitedSources(msg.content, sources)
                      return (
                        <>
                          <div
                            className="ai-answer"
                            style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                            dangerouslySetInnerHTML={{
                              __html: renderAnswerWithCitations(msg.content, cited),
                            }}
                            onClick={(e) => {
                              const target = e.target as HTMLElement
                              if (target.classList.contains('cite-badge')) {
                                const citeNum = target.getAttribute('data-cite')
                                const card = document.getElementById(`cite-card-${msg.id}-${citeNum}`)
                                if (card) {
                                  card.scrollIntoView({ behavior: 'smooth', block: 'center' })
                                  card.style.background = '#f0eefc'
                                  setTimeout(() => { card.style.background = '' }, 2000)
                                }
                              }
                            }}
                          />
                          {cited.length > 0 && (
                            <CitationBar msgId={msg.id} citedSources={cited} />
                          )}
                        </>
                      )
                    })()
                  )}
                </div>
              </div>
            ))}

            {/* Loading indicator */}
            {loading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
                <RobotOutlined style={{ color: 'var(--color-primary, #5645d4)' }} />
                <Spin size="small" />
                <Text type="secondary" style={{ fontSize: 13 }}>
                  正在检索知识库并生成回答...
                </Text>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* ── Input Area ── */}
      <div
        style={{
          padding: '12px 24px 16px',
          borderTop: '1px solid var(--color-hairline, #e5e3df)',
          background: '#ffffff',
          flexShrink: 0,
        }}
      >
        <div style={{ maxWidth: 800, margin: '0 auto', display: 'flex', gap: 10 }}>
          <Input.TextArea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入您的问题，如「动火作业需要什么安全措施？」"
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
          按 Enter 发送，Shift + Enter 换行 · 回答基于知识库法规原文
        </p>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// CitationBar — regulation source reference list
// Receives already-deduped, already-ordered cited sources.
// Uses sequential numbering [1][2][3].
// Format:
//   引用法规来源（N 篇）
//   ─────────────────────────────────
//    [1] GB 3836.1-2010 爆炸性环境…  查看原文 →
//    [2] 消防安全管理制度               查看原文 →
//   ─────────────────────────────────
// ═══════════════════════════════════════════════════════════════

function CitationBar({
  msgId,
  citedSources,
}: {
  msgId: string
  citedSources: InfoQuerySource[]
}) {
  if (!citedSources || citedSources.length === 0) return null

  return (
    <div style={{ marginTop: 20, width: '100%' }}>
      <Text type="secondary" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, marginBottom: 6 }}>
        <FileTextOutlined />
        引用法规来源（{citedSources.length} 篇）
      </Text>

      <div style={{ height: 1, background: '#e5e3df', marginBottom: 8 }} />

      {citedSources.map((s, i) => {
        const n = i + 1 // sequential display number
        return (
          <div
            key={n}
            id={`cite-card-${msgId}-${n}`}
            style={{
              display: 'flex', alignItems: 'baseline', gap: 8, padding: '4px 0',
              fontSize: 13, lineHeight: 1.7, color: '#1a1a1a',
              transition: 'background 0.3s', borderRadius: 4,
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 13, color: '#1a1a1a', flexShrink: 0 }}>
              [{n}]
            </span>

            <span style={{ flex: 1, minWidth: 0 }}>
              <strong>{s.doc_title}</strong>
              {s.article_ref && (
                <span style={{ color: '#787671', fontSize: 12 }}>{' — '}{s.article_ref}</span>
              )}
            </span>

            {s.feishu_url ? (
              <a
                href={s.feishu_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontSize: 12, color: 'var(--color-primary, #5645d4)',
                  whiteSpace: 'nowrap', flexShrink: 0, textDecoration: 'none', fontWeight: 500,
                }}
              >
                查看原文 →
              </a>
            ) : null}
          </div>
        )
      })}

      <div style={{ height: 1, background: '#e5e3df', marginTop: 6 }} />
    </div>
  )
}
