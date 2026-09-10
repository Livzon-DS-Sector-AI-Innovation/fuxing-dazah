'use client'

// 审计记录抽屉（design.md §2.7）：按域拉取变更历史，before/after JSON 对比
// 时间（本地化）| 操作人 | 动作 Tag | 对象（domain·kind mono）| 变更摘要（关键字段 before→after）| 详情展开
// 分页 pageSize 10；空则 Empty「暂无变更记录」

import { useEffect, useState } from 'react'
import { App, Drawer, Empty, Skeleton, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { fetchBitableAudits } from '@/actions/safety'
import type { BitableAuditItem } from '@/types/safety'
import { ACTION_TAG_UI, MONO_FONT, UI } from './bitableConfigConstants'

interface BitableAuditDrawerProps {
  open: boolean
  domain: string | null
  onClose: () => void
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '空'
  if (typeof v === 'boolean') return v ? '启用' : '停用'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** 变更摘要：before/after 差异的关键字段，如 `app_token: bascnA→bascnB`、`enabled: 启用→停用` */
function diffSummary(item: BitableAuditItem): string {
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

function DiffView({ item }: { item: BitableAuditItem }) {
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

export default function BitableAuditDrawer({ open, domain, onClose }: BitableAuditDrawerProps) {
  const { message } = App.useApp()
  const [items, setItems] = useState<BitableAuditItem[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !domain) return
    setLoading(true)
    setItems([])
    fetchBitableAudits(domain, 50)
      .then((res) => {
        if (res.code === 200 && res.data) {
          setItems(res.data)
        } else {
          message.error(res.message || '加载审计记录失败')
        }
      })
      .finally(() => setLoading(false))
  }, [open, domain, message])

  const columns: ColumnsType<BitableAuditItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v: string) => <span style={{ fontSize: 12, color: UI.slate }}>{formatTime(v)}</span>,
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
      width: 100,
      render: (v: string) => {
        const ui = ACTION_TAG_UI[v] ?? { label: v, color: 'default' }
        return (
          <Tag color={ui.color} style={{ borderRadius: 6, fontWeight: 600 }}>
            {ui.label}
          </Tag>
        )
      },
    },
    {
      title: '对象',
      key: 'object',
      width: 170,
      render: (_, r) => (
        <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel, whiteSpace: 'nowrap' }}>
          {r.domain}
          {r.kind ? ` · ${r.kind}` : ''}
        </span>
      ),
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
    <Drawer
      title={
        <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>
          变更审计{domain ? ` · ${domain}` : ''}
        </span>
      }
      width={760}
      open={open}
      onClose={onClose}
      destroyOnHidden
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无变更记录" />
      ) : (
        <Table<BitableAuditItem>
          rowKey={(r, i) => r.id ?? `${r.created_at}-${i}`}
          size="small"
          columns={columns}
          dataSource={items}
          pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
          expandable={{
            expandedRowRender: (r) => <DiffView item={r} />,
            rowExpandable: (r) => Boolean(r.before_json || r.after_json),
          }}
          scroll={{ x: 640 }}
        />
      )}
    </Drawer>
  )
}
