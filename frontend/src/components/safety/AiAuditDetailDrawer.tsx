'use client'

import { useEffect } from 'react'
import { Alert, Button, Collapse, Drawer, Space, Tag, Typography } from 'antd'
import { FileTextOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import type { AiCallAuditDetail } from '@/types/safety'
import {
  ChannelTag,
  MONO_FONT,
  ScenarioTag,
  StatusDot,
  UI,
  absoluteTime,
  formatCacheRate,
  formatLatency,
  latencyColor,
  parseMessages,
} from './aiAuditConstants'

const { Text } = Typography

// Phoenix 观测平台地址（二期）；未配置时不渲染跳转按钮
const PHOENIX_URL = process.env.NEXT_PUBLIC_PHOENIX_URL || ''

interface AiAuditDetailDrawerProps {
  open: boolean
  detail: AiCallAuditDetail | null
  onClose: () => void
  onPrev: () => void
  onNext: () => void
  hasPrev: boolean
  hasNext: boolean
}

/** 元信息项：标签（11px stone）+ 值（14px ink） */
function MetaItem({
  label,
  children,
  span = 1,
}: {
  label: string
  children: React.ReactNode
  span?: number
}) {
  return (
    <div style={{ gridColumn: `span ${span}`, minWidth: 0 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: 0.5,
          color: UI.stone,
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 13, color: UI.ink, wordBreak: 'break-all' }}>{children}</div>
    </div>
  )
}

/** 对话气泡：role 标签 + 分色气泡体 */
function Bubble({ role, content }: { role: string; content: string }) {
  const isUser = role === 'user'
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, color: UI.stone, margin: '0 4px 2px' }}>
        {role}
      </div>
      <div
        style={{
          maxWidth: '85%',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          fontSize: 13,
          lineHeight: 1.6,
          color: UI.charcoal,
          padding: '8px 12px',
          borderRadius: 12,
          background: isUser ? UI.skyTint : UI.canvas,
          border: isUser ? 'none' : `1px solid ${UI.hairline}`,
        }}
      >
        {content}
      </div>
    </div>
  )
}

/** 原文回退块（messages 解析失败时，如隐患识别的拼接 prompt） */
function RawBlock({ text }: { text: string }) {
  return (
    <div
      style={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        fontFamily: MONO_FONT,
        fontSize: 12,
        lineHeight: 1.6,
        color: UI.charcoal,
        background: UI.surface,
        padding: 12,
        borderRadius: 8,
        maxHeight: 300,
        overflow: 'auto',
      }}
    >
      {text}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>
      {children}
    </div>
  )
}

export default function AiAuditDetailDrawer({
  open,
  detail,
  onClose,
  onPrev,
  onNext,
  hasPrev,
  hasNext,
}: AiAuditDetailDrawerProps) {
  // ── 键盘 ←/→ 翻阅（输入框聚焦时不响应） ──
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return
      }
      if (e.key === 'ArrowLeft' && hasPrev) onPrev()
      if (e.key === 'ArrowRight' && hasNext) onNext()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, hasPrev, hasNext, onPrev, onNext])

  const messages = detail ? parseMessages(detail.input_text) : null

  return (
    <Drawer
      size={720}
      open={open}
      onClose={onClose}
      title={
        detail ? (
          <Space size={8}>
            <StatusDot status={detail.status} degradationLevel={detail.degradation_level} />
            <ScenarioTag scenario={detail.scenario} />
            <ChannelTag channel={detail.channel} />
            {detail.user_name && (
              <span style={{ fontSize: 13, fontWeight: 500, color: UI.charcoal }}>
                {detail.user_name}
              </span>
            )}
            <span style={{ fontSize: 13, fontWeight: 400, color: UI.slate }}>
              {absoluteTime(detail.created_at)}
            </span>
          </Space>
        ) : (
          'AI 调用详情'
        )
      }
      extra={
        <Space size={4}>
          <Button
            size="small"
            icon={<LeftOutlined />}
            disabled={!hasPrev}
            onClick={onPrev}
            title="上一条（←）"
          />
          <Button
            size="small"
            icon={<RightOutlined />}
            disabled={!hasNext}
            onClick={onNext}
            title="下一条（→）"
          />
          {PHOENIX_URL && detail?.trace_id && (
            <Button
              size="small"
              type="link"
              href={PHOENIX_URL}
              target="_blank"
              title="在 Phoenix 中用 trace_id 搜索调用链"
            >
              在 Phoenix 中查看 ↗
            </Button>
          )}
        </Space>
      }
    >
      {detail && (
        <>
          {/* ── 元信息条（surface 底一整条网格） ── */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '12px 16px',
              background: UI.surface,
              borderRadius: 8,
              padding: '12px 16px',
            }}
          >
            <MetaItem label="模型">{detail.model}</MetaItem>
            <MetaItem label="TOKEN 入 / 出">
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                {detail.input_tokens?.toLocaleString() ?? '—'} /{' '}
                {detail.output_tokens?.toLocaleString() ?? '—'}
              </span>
            </MetaItem>
            <MetaItem label="前缀缓存命中">
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatCacheRate(detail.cache_hit_tokens, detail.cache_miss_tokens)}
                {' · '}
                命中 {detail.cache_hit_tokens?.toLocaleString() ?? '—'} / 未命中{' '}
                {detail.cache_miss_tokens?.toLocaleString() ?? '—'}
              </span>
            </MetaItem>
            <MetaItem label="耗时">
              <span style={{ color: latencyColor(detail.latency_ms) }}>
                {formatLatency(detail.latency_ms)}
              </span>
            </MetaItem>
            <MetaItem label="PROMPT 版本">
              <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>
                {detail.prompt_version ?? '—'}
              </span>
            </MetaItem>
            <MetaItem label="用户">{detail.user_name ?? '—'}</MetaItem>
            <MetaItem label="渠道">
              <ChannelTag channel={detail.channel} />
            </MetaItem>
            <MetaItem label="资源">
              {detail.resource_id
                ? `${detail.resource_type ?? ''} ${detail.resource_id.slice(0, 8)}…`
                : '—'}
            </MetaItem>
            <MetaItem label="检索降级">{detail.degradation_level ?? '—'}</MetaItem>
            <MetaItem label="TRACE ID">
              {detail.trace_id ? (
                <Text
                  copyable={{ text: detail.trace_id }}
                  style={{ fontFamily: MONO_FONT, fontSize: 12 }}
                >
                  {detail.trace_id.slice(0, 12)}…
                </Text>
              ) : (
                '—'
              )}
            </MetaItem>
            <MetaItem label="会话" span={2}>
              {detail.session_id ? (
                <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>
                  {detail.session_id}
                </span>
              ) : (
                '—'
              )}
            </MetaItem>
          </div>

          {/* ── 错误信息 ── */}
          {detail.error && (
            <Alert
              type="error"
              showIcon
              message="调用失败"
              description={<span style={{ whiteSpace: 'pre-wrap' }}>{detail.error}</span>}
              style={{ marginTop: 16 }}
            />
          )}

          {/* ── 引用法规 ── */}
          {detail.cited_sources && detail.cited_sources.length > 0 && (
            <>
              <SectionTitle>引用法规</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {detail.cited_sources.map((s, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      border: `1px solid ${UI.hairline}`,
                      borderRadius: 8,
                      padding: '6px 12px',
                      fontSize: 13,
                      color: UI.charcoal,
                    }}
                  >
                    <FileTextOutlined style={{ color: UI.steel }} />
                    <span>
                      《{s.doc_title ?? '未知文档'}》
                      {s.article_ref ? ` ${s.article_ref}` : ''}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* ── 禁语命中 ── */}
          {detail.guard_hits && detail.guard_hits.length > 0 && (
            <>
              <SectionTitle>禁语命中</SectionTitle>
              <Space wrap>
                {detail.guard_hits.map((g) => (
                  <Tag key={g} color="volcano">
                    {g}
                  </Tag>
                ))}
              </Space>
            </>
          )}

          {/* ── 对话内容 ── */}
          <SectionTitle>
            对话内容
            {detail.input_truncated && (
              <Tag style={{ marginLeft: 8 }} color="orange">
                输入已截断
              </Tag>
            )}
            {detail.output_truncated && (
              <Tag style={{ marginLeft: 8 }} color="orange">
                输出已截断
              </Tag>
            )}
          </SectionTitle>

          {messages ? (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                maxHeight: 480,
                overflow: 'auto',
                padding: 4,
              }}
            >
              {messages.map((m, i) =>
                m.role === 'system' ? (
                  <Collapse
                    key={i}
                    size="small"
                    ghost
                    style={{ background: UI.grayTint, borderRadius: 8 }}
                    items={[
                      {
                        key: String(i),
                        label: (
                          <span style={{ fontSize: 12, fontWeight: 600, color: UI.slate }}>
                            System Prompt · {m.content.length} 字
                          </span>
                        ),
                        children: (
                          <div
                            style={{
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              fontSize: 12,
                              lineHeight: 1.6,
                              color: UI.slate,
                              maxHeight: 280,
                              overflow: 'auto',
                            }}
                          >
                            {m.content}
                          </div>
                        ),
                      },
                    ]}
                  />
                ) : (
                  <Bubble key={i} role={m.role} content={m.content} />
                ),
              )}
              {detail.output_text && <Bubble role="assistant" content={detail.output_text} />}
            </div>
          ) : (
            <>
              {detail.input_text && <RawBlock text={detail.input_text} />}
              {detail.output_text && (
                <>
                  <SectionTitle>输出</SectionTitle>
                  <RawBlock text={detail.output_text} />
                </>
              )}
            </>
          )}
        </>
      )}
    </Drawer>
  )
}
