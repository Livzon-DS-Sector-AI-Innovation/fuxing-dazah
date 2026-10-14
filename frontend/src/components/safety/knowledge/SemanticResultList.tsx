'use client'

import { Empty, Skeleton, Tag, Tooltip } from 'antd'
import { FileText, Quote } from 'lucide-react'
import type { SemanticSearchResult } from '@/types/safety'

interface Props {
  results: SemanticSearchResult[]
  loading: boolean
  mode: 'engine' | 'keyword'
  onOpenDetail: (id: string) => void
}

/**
 * 条款级检索结果（参考 ragplus 会话引用风格）：
 * [n] 编号 + 法规名 + 条款定位 chips + 相似度 + 命中片段引用块。
 * keyword 模式（开关关/回退）复用同一布局，条款区显示关键词。
 */
export default function SemanticResultList({ results, loading, mode, onOpenDetail }: Props) {
  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} active title={{ width: '40%' }} paragraph={{ rows: 2 }} />
        ))}
      </div>
    )
  }

  if (results.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="未检索到相关法规"
        style={{ padding: '48px 0' }}
      >
        <span style={{ fontSize: 12, color: 'var(--color-stone, #a4a097)' }}>
          可换更具体的业务表述再试（如「动火作业前需要办理什么手续」）
        </span>
      </Empty>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {results.map((r, idx) => {
        const refs = r.matched_refs || []
        const sim = typeof r.similarity === 'number' ? r.similarity : null
        return (
          <div
            key={`${r.id}-${idx}`}
            style={{
              border: '1px solid var(--color-hairline, #e5e3df)',
              borderRadius: 12,
              padding: '14px 16px',
              background: 'var(--color-canvas, #ffffff)',
            }}
          >
            {/* 标题行：[n] 法规名 + 分类 + 相似度 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  minWidth: 22,
                  height: 22,
                  borderRadius: 6,
                  background: 'rgba(86, 69, 212, 0.08)',
                  color: 'var(--color-primary, #5645d4)',
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {idx + 1}
              </span>
              <button
                type="button"
                onClick={() => r.id && onOpenDetail(r.id)}
                disabled={!r.id}
                style={{
                  border: 'none',
                  background: 'none',
                  padding: 0,
                  cursor: r.id ? 'pointer' : 'default',
                  fontSize: 15,
                  fontWeight: 600,
                  color: 'var(--color-charcoal, #2b2a27)',
                  textAlign: 'left',
                }}
              >
                《{r.title}》
              </button>
              {r.category ? (
                <Tag bordered={false} style={{ fontSize: 12 }}>
                  {r.category === 'laws_regulations' ? '法规' : r.category}
                </Tag>
              ) : null}
              <div style={{ flex: 1 }} />
              {sim !== null && (
                <Tooltip title={`引擎相似度 ${sim.toFixed(2)}（归一 0~1）`}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      fontSize: 12,
                      color: 'var(--color-steel, #787671)',
                    }}
                  >
                    <span
                      style={{
                        display: 'inline-block',
                        width: 56,
                        height: 6,
                        borderRadius: 999,
                        background: 'var(--color-hairline, #e5e3df)',
                        overflow: 'hidden',
                      }}
                    >
                      <span
                        style={{
                          display: 'block',
                          height: '100%',
                          width: `${Math.round(Math.min(sim, 1) * 100)}%`,
                          borderRadius: 999,
                          background: 'var(--color-primary, #5645d4)',
                          opacity: 0.75,
                        }}
                      />
                    </span>
                    {sim.toFixed(2)}
                  </span>
                </Tooltip>
              )}
            </div>

            {/* 条款定位 chips */}
            {refs.length > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
                {refs.map((ref, i) => (
                  <span
                    key={`${ref}-${i}`}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      borderRadius: 999,
                      padding: '2px 10px',
                      fontSize: 12,
                      fontWeight: 500,
                      background: 'rgba(86, 69, 212, 0.06)',
                      color: 'var(--color-primary, #5645d4)',
                      border: '1px solid rgba(86, 69, 212, 0.18)',
                    }}
                  >
                    <FileText size={11} />
                    {ref}
                  </span>
                ))}
              </div>
            )}
            {refs.length === 0 && r.match_reason && (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--color-steel, #787671)' }}>
                {r.match_reason}
              </div>
            )}

            {/* 命中片段引用块 */}
            {r.summary && (
              <div
                style={{
                  marginTop: 10,
                  display: 'flex',
                  gap: 8,
                  padding: '10px 12px',
                  borderRadius: 8,
                  background: 'var(--color-surface, #f7f6f3)',
                  borderLeft: '3px solid rgba(86, 69, 212, 0.35)',
                  fontSize: 13,
                  lineHeight: 1.7,
                  color: 'var(--color-charcoal, #2b2a27)',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  maxHeight: 120,
                  overflow: 'hidden',
                }}
              >
                <Quote size={13} style={{ flexShrink: 0, marginTop: 4, opacity: 0.4 }} />
                <span>{r.summary}</span>
              </div>
            )}
          </div>
        )
      })}
      {mode === 'keyword' && (
        <div style={{ fontSize: 12, color: 'var(--color-stone, #a4a097)', textAlign: 'center' }}>
          当前为关键词过滤模式（引擎开关关闭时的回退路径）
        </div>
      )}
    </div>
  )
}
