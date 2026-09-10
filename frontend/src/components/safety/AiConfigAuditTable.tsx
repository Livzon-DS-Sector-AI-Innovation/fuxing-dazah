'use client'

// AI 配置变更审计表（design.md §3.3）：时间/操作人/动作/配置组/变更摘要 + 展开 before/after
// 仿 BitableAuditDrawer 的 DiffView 渲染范式（仅复制实现，不抽共享组件——避免跨功能回归）
// 挂载/refreshKey 变化 → fetchAiConfigAudits(50)；loading/error/retry/分页（pageSize 10）自持。

import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Empty, Skeleton, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { fetchAiConfigAudits } from '@/actions/safety'
import type { AiConfigAuditItem } from '@/types/safety'
import {
  AI_AUDIT_ACTION_UI,
  AI_PROFILE_UI,
  CARD_STYLE,
  MONO_FONT,
  UI,
} from './schedulerConfigConstants'

interface AiConfigAuditTableProps {
  /** 保存成功后 +1 触发重拉（仅已挂载时生效） */
  refreshKey?: number
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '空'
  if (typeof v === 'boolean') return v ? '启用' : '停用'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** 变更摘要：before/after 差异的关键字段，前 3 项 + 「…共 N 项」 */
function diffSummary(item: AiConfigAuditItem): string {
  const before = item.before_json
  const after = item.after_json
  const keys = new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])
  const changes: string[] = []
  for (const k of keys) {
    const b = before?.[k]
    const a = after?.[k]
    if (JSON.stringify(b) !== JSON.stringify(a)) {
      changes.push(`${k}: ${fmtVal(b)} → ${fmtVal(a)}`)
    }
  }
  if (changes.length === 0) return '—'
  return changes.slice(0, 3).join('；') + (changes.length > 3 ? `；…共 ${changes.length} 项` : '')
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function DiffView({ item }: { item: AiConfigAuditItem }) {
  if (!item.before_json && !item.after_json) {
    return <div style={{ fontSize: 12, color: UI.muted, padding: '8px 0' }}>该操作无变更数据</div>
  }
  const block = (title: string, json: Record<string, unknown> | null | undefined) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: UI.slate, marginBottom: 4 }}>{title}</div>
      <pre
        style={{
          margin: 0,
          fontFamily: MONO_FONT,
          fontSize: 12,
          color: UI.ink,
          background: UI.surface,
          border: `1px solid ${UI.hairlineSoft}`,
          borderRadius: 6,
          padding: 8,
          maxHeight: 240,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {json ? JSON.stringify(json, null, 2) : '无'}
      </pre>
    </div>
  )
  return (
    <div style={{ display: 'flex', gap: 12 }}>
      {block('变更前（before）', item.before_json)}
      {block('变更后（after）', item.after_json)}
    </div>
  )
}

export default function AiConfigAuditTable({ refreshKey = 0 }: AiConfigAuditTableProps) {
  const [items, setItems] = useState<AiConfigAuditItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchAiConfigAudits({ limit: 50 })
      if (res.code === 200 && res.data) {
        setItems(res.data)
      } else {
        setError(res.message || '加载审计记录失败')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  // 挂载/refreshKey 变化：setState 全部发生在异步续体中（react-hooks/set-state-in-effect）
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const res = await fetchAiConfigAudits({ limit: 50 })
      if (cancelled) return
      if (res.code === 200 && res.data) {
        setItems(res.data)
        setError(null)
      } else {
        setError(res.message || '加载审计记录失败')
      }
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  const columns: ColumnsType<AiConfigAuditItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string) => (
        <span style={{ fontSize: 12, color: UI.slate }}>{v ? formatTime(v) : '—'}</span>
      ),
    },
    {
      title: '操作人',
      dataIndex: 'operator_name',
      key: 'operator_name',
      width: 90,
      render: (v: string | null | undefined) => (
        <span style={{ fontSize: 13, color: v ? UI.ink : UI.muted }}>{v || '—'}</span>
      ),
    },
    {
      title: '动作',
      dataIndex: 'action',
      key: 'action',
      width: 90,
      render: (v: string) => {
        const ui = AI_AUDIT_ACTION_UI[v] ?? { label: v, color: 'default' }
        return (
          <Tag color={ui.color} style={{ borderRadius: 6, fontWeight: 600 }}>
            {ui.label}
          </Tag>
        )
      },
    },
    {
      title: '配置组',
      key: 'profile',
      width: 150,
      render: (_, r) => {
        const ui = AI_PROFILE_UI[r.profile as keyof typeof AI_PROFILE_UI]
        return (
          <span style={{ whiteSpace: 'nowrap' }}>
            <span style={{ fontSize: 13, color: UI.ink }}>{ui?.label ?? r.profile}</span>
            <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel, marginLeft: 6 }}>
              {r.profile}
            </span>
          </span>
        )
      },
    },
    {
      title: '变更摘要',
      key: 'summary',
      render: (_, r) => (
        <span style={{ fontSize: 12, color: UI.slate }}>{diffSummary(r)}</span>
      ),
    },
  ]

  return (
    <div style={{ ...CARD_STYLE, padding: 16 }}>
      {loading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message={<span style={{ fontSize: 13 }}>审计记录加载失败</span>}
          description={<span style={{ fontSize: 12, color: UI.muted }}>{error}</span>}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无变更记录" />
      ) : (
        <Table<AiConfigAuditItem>
          rowKey={(r, i) => r.id ?? `${r.created_at}-${i}`}
          size="small"
          columns={columns}
          dataSource={items}
          pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
          expandable={{
            expandedRowRender: (r) => <DiffView item={r} />,
            rowExpandable: (r) => Boolean(r.before_json || r.after_json),
          }}
          scroll={{ x: 720 }}
        />
      )}
    </div>
  )
}
