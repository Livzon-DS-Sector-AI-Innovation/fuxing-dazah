'use client'

// 六类配置变更审计共享组件（模型/场景/运行参数/多维表格/定时任务/推送任务）
// 对齐 safety/AiConfigAuditTable 范式：时间/操作人/动作/对象/变更摘要 + 展开 before/after。
// 懒加载：Collapse 首次展开才取数（fetchWarehouseConfigAudits 按 kind 分发）；
// 暴露 refresh()（ConfigAuditHandle）供保存成功后顶刷。

import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'
import { Alert, Button, Collapse, Empty, Skeleton, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { getWarehouseConfigAudits } from '@/actions/warehouse'
import type { WarehouseConfigAuditBase, WarehouseConfigAuditKind } from '@/types/warehouse'
import { AUDIT_ACTION_UI, CARD_STYLE, MONO_FONT, UI, formatTime } from './systemConfigConstants'

export interface ConfigAuditHandle {
  refresh: () => void
}

/** kind → 「对象」列取值键与取数说明 */
const KIND_META: Record<WarehouseConfigAuditKind, { entityKey: string; label: string }> = {
  'ai-model': { entityKey: 'profile', label: 'AI 模型配置审计' },
  'ai-scenario': { entityKey: 'scenario', label: 'AI 场景配置审计' },
  runtime: { entityKey: 'key', label: '运行参数审计' },
  bitable: { entityKey: 'table_key', label: '多维表格连接审计' },
  scheduler: { entityKey: 'job_name', label: '定时任务审计' },
  push: { entityKey: 'task_name', label: '推送任务审计' },
}

type AuditRow = WarehouseConfigAuditBase & Record<string, unknown>

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '空'
  if (typeof v === 'boolean') return v ? '启用' : '停用'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** 变更摘要：before/after 差异的关键字段，前 3 项 + 「…共 N 项」 */
function diffSummary(item: WarehouseConfigAuditBase): string {
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

function DiffView({ item }: { item: WarehouseConfigAuditBase }) {
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

interface ConfigAuditSectionProps {
  kind: WarehouseConfigAuditKind
}

const ConfigAuditSection = forwardRef<ConfigAuditHandle, ConfigAuditSectionProps>(
  function ConfigAuditSection({ kind }, ref) {
    const meta = KIND_META[kind]
    const [items, setItems] = useState<AuditRow[] | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const loadedRef = useRef(false)

    const load = useCallback(async () => {
      setLoading(true)
      setError(null)
      try {
        const rows = await getWarehouseConfigAudits(kind, 50)
        setItems(rows as AuditRow[])
        loadedRef.current = true
      } catch (e) {
        setError(e instanceof Error ? e.message : '加载审计记录失败')
      } finally {
        setLoading(false)
      }
    }, [kind])

    useImperativeHandle(ref, () => ({
      refresh: () => {
        if (loadedRef.current) void load()
      },
    }))

    const columns: ColumnsType<AuditRow> = [
      {
        title: '时间',
        dataIndex: 'created_at',
        key: 'created_at',
        width: 170,
        render: (v: string) => (
          <span style={{ fontSize: 12, color: UI.slate }}>{formatTime(v)}</span>
        ),
      },
      {
        title: '操作人',
        dataIndex: 'operator_name',
        key: 'operator_name',
        width: 100,
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
          const ui = AUDIT_ACTION_UI[v] ?? { label: v, color: 'default' }
          return (
            <Tag color={ui.color} style={{ borderRadius: 6, fontWeight: 600 }}>
              {ui.label}
            </Tag>
          )
        },
      },
      {
        title: '对象',
        key: 'entity',
        width: 180,
        render: (_, r) => {
          const entity = String(r[meta.entityKey] ?? '—')
          return (
            <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>{entity}</span>
          )
        },
      },
      {
        title: '变更摘要',
        key: 'summary',
        render: (_, r) => <span style={{ fontSize: 12, color: UI.slate }}>{diffSummary(r)}</span>,
      },
    ]

    return (
      <Collapse
        ghost
        style={{ ...CARD_STYLE, marginTop: 20, padding: '4px 16px' }}
        items={[
          {
            key: 'audits',
            label: (
              <span style={{ fontSize: 13, fontWeight: 600, color: UI.slate }}>
                {meta.label}（最近 50 条）
              </span>
            ),
            children: (
              <div style={{ paddingBottom: 12 }}>
                {loading && items === null ? (
                  <Skeleton active paragraph={{ rows: 6 }} />
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
                ) : !items || items.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无变更记录" />
                ) : (
                  <Table<AuditRow>
                    rowKey={(r, i) => String(r.id ?? `${r.created_at}-${i}`)}
                    size="small"
                    columns={columns}
                    dataSource={items}
                    pagination={{
                      pageSize: 10,
                      showSizeChanger: false,
                      showTotal: (t) => `共 ${t} 条`,
                    }}
                    expandable={{
                      expandedRowRender: (r) => <DiffView item={r} />,
                      rowExpandable: (r) => Boolean(r.before_json || r.after_json),
                    }}
                    scroll={{ x: 760 }}
                  />
                )}
              </div>
            ),
          },
        ]}
        // 首次展开才取数（懒加载；后续展开不再重复拉）
        onChange={(keys) => {
          if (keys.length > 0 && !loadedRef.current && !loading) void load()
        }}
      />
    )
  },
)

export default ConfigAuditSection
