'use client'

// AI 场景配置变更审计表（design.md §7）：时间/操作人/动作/场景/变更摘要 + 展开 before/after
// 复刻 AiConfigAuditTable 范式（仅复制实现，不抽共享组件——避免跨功能回归），唯一差异：配置组列→场景列
// 挂载/refreshKey 变化 → fetchAiScenarioAudits({limit: 50})；loading/error/retry/分页（pageSize 10）自持。

import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Empty, Skeleton, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { fetchAiScenarioAudits } from '@/actions/safety'
import type { AiScenarioAuditItem } from '@/types/safety'
import {
  AI_AUDIT_ACTION_UI,
  CARD_STYLE,
  MONO_FONT,
  UI,
} from './schedulerConfigConstants'

interface AiScenarioAuditTableProps {
  /** 场景配置保存成功后 +1 触发重拉（仅已挂载时生效） */
  refreshKey?: number
  /** 场景 id → 中文名映射（来源于 fixtures data.functions；缺 label 时显示原始 id） */
  scenarioLabels?: Record<string, string>
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '空'
  if (typeof v === 'boolean') return v ? '启用' : '停用'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** 变更摘要：before/after 差异的关键字段，前 3 项 + 「…共 N 项」 */
function diffSummary(item: AiScenarioAuditItem): string {
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

function DiffView({ item }: { item: AiScenarioAuditItem }) {
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

export default function AiScenarioAuditTable({
  refreshKey = 0,
  scenarioLabels,
}: AiScenarioAuditTableProps) {
  const [items, setItems] = useState<AiScenarioAuditItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchAiScenarioAudits({ limit: 50 })
      if (res.code === 200 && res.data) {
        setItems(res.data)
      } else {
        setError(res.message || '加载场景审计记录失败')
      }
    } catch (e) {
      // MINOR5 修复：server action 传输层可能抛（fetchApi 本身不抛）；
      // 捕获 → 错误态，不卡 loading（finally 兜底）
      setError(e instanceof Error ? e.message : '加载场景审计记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 挂载/refreshKey 变化：与重试按钮共用同一 load() 回调（MINOR5 修复，消除重复取数逻辑）。
  // setState 全部发生在异步续体中（react-hooks/set-state-in-effect）：经 IIFE 的 await
  // 边界后再调用 load，避免 effect 同步触发 setLoading(true)
  useEffect(() => {
    void (async () => {
      await load()
    })()
  }, [load, refreshKey])

  const columns: ColumnsType<AiScenarioAuditItem> = [
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
      title: '场景',
      key: 'scenario',
      width: 150,
      render: (_, r) => {
        const label = scenarioLabels?.[r.scenario]
        return (
          <span style={{ whiteSpace: 'nowrap' }}>
            <span style={{ fontSize: 13, color: UI.ink }}>{label ?? r.scenario}</span>
            <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel, marginLeft: 6 }}>
              {r.scenario}
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
          message={<span style={{ fontSize: 13 }}>场景审计记录加载失败</span>}
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
        <Table<AiScenarioAuditItem>
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
