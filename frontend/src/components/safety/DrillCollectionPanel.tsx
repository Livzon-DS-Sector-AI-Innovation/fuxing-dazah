'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Empty, Select, Table, Tag } from 'antd'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import { getCollectionRecords, getCollectionStats } from '@/actions/safety'
import type { CollectionRecord, CollectionStats } from '@/types/safety'
import { CARD_STYLE, T, UI } from './emergencyDrillConstants'

// ── 解析状态映射 ──

const PARSE_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: '待解析', color: '#0075de', bg: T.sky },
  parsed: { label: '已解析', color: '#1aae39', bg: T.mint },
  failed: { label: '解析失败', color: T.warning, bg: T.peach },
}

const PARSE_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待解析' },
  { value: 'parsed', label: '已解析' },
  { value: 'failed', label: '解析失败' },
]

// ── KPI ──

function KpiCard({ label, value, bg, valueColor }: { label: string; value: string; bg?: string; valueColor?: string }) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: '12px 14px', background: bg ?? UI.canvas }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.stone }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 600, lineHeight: 1.3, marginTop: 2, color: valueColor ?? UI.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
    </div>
  )
}

// ── 主组件 ──

export default function DrillCollectionPanel() {
  const { message } = App.useApp()

  const [parseStatus, setParseStatus] = useState('')
  const [rows, setRows] = useState<CollectionRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<CollectionStats | null>(null)

  const loadList = useCallback(async (p: number, ps: number) => {
    setLoading(true)
    try {
      const res = await getCollectionRecords({
        page: p, page_size: ps,
        parse_status: parseStatus || undefined,
      })
      if (res.code === 200 && res.data) {
        setRows(res.data)
        setTotal(res.meta?.total ?? 0)
      }
    } finally { setLoading(false) }
  }, [parseStatus])

  const loadStats = useCallback(async () => {
    try {
      const res = await getCollectionStats()
      if (res.code === 200 && res.data) setStats(res.data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadList(1, pageSize); loadStats() }, []) // eslint-disable-line

  const columns: ColumnsType<CollectionRecord> = useMemo(() => [
    {
      title: '日期', dataIndex: 'upload_date', key: 'upload_date', width: 110,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD') : '-',
    },
    {
      title: '附件', dataIndex: 'attachment', key: 'attachment', width: 200, ellipsis: true,
      render: (a: CollectionRecord['attachment']) => {
        if (!a?.length) return '-'
        return a.map((f, i) => <Tag key={i} style={{ marginBottom: 2 }}>{f.name}</Tag>)
      },
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 140, ellipsis: true },
    {
      title: '上传人', key: 'person', width: 100,
      render: (_: unknown, r: CollectionRecord) => r.person_data?.name || '-',
    },
    {
      title: '解析状态', dataIndex: 'parse_status', key: 'parse_status', width: 100,
      render: (s: string) => {
        const ui = PARSE_STATUS_UI[s]
        if (!ui) return s || '-'
        return <Tag style={{ color: ui.color, background: ui.bg, border: 'none', fontWeight: 600 }}>{ui.label}</Tag>
      },
    },
    {
      title: '统计记录', dataIndex: 'stats_record_id', key: 'stats_record_id', width: 120,
      render: (id: string) => id ? <Tag color="green">已创建</Tag> : '-',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 150,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD HH:mm') : '-',
    },
  ], [])

  return (
    <div style={{ padding: '0 0 32px' }}>
      {/* KPI 卡片 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="收录总数" value={String(stats?.total ?? '-')} bg={T.lavender} valueColor={T.primary} />
        <KpiCard label="已解析" value={String(stats?.parsed ?? '-')} bg={T.mint} valueColor={T.success} />
        <KpiCard label="待解析" value={String(stats?.pending ?? '-')} bg={T.sky} valueColor="#005bab" />
        <KpiCard label="解析失败" value={String(stats?.failed ?? '-')} bg={T.peach} valueColor={T.warning} />
      </div>

      {/* 筛选 + 表格 */}
      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          <span style={{ fontSize: 13, color: UI.steel, lineHeight: '32px' }}>上传演练计划附件到飞书「演练计划收录」表，平台自动解析并创建统计记录</span>
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          <Select value={parseStatus} onChange={(v) => { setParseStatus(v); setPage(1); loadList(1, pageSize) }}
            options={PARSE_STATUS_FILTER} style={{ width: 140 }} placeholder="解析状态" allowClear />
        </div>

        <Table<CollectionRecord>
          columns={columns} dataSource={rows} rowKey="id"
          loading={loading} scroll={{ x: 900 }}
          locale={{ emptyText: <Empty description="暂无收录记录，请在飞书「演练计划收录」表中上传附件" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); loadList(p, ps) },
          }}
          size="middle"
        />
      </div>
    </div>
  )
}
