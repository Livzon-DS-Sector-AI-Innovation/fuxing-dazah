'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Select, Table, Tag } from 'antd'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import { getCollectionRecords, getCollectionStats } from '@/actions/safety'
import type { CollectionRecord, CollectionStats } from '@/types/safety'
import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'

// ── 解析状态映射（ui-kit 语义 tone：待解析 info / 已解析 ok / 失败 danger） ──

const PARSE_STATUS_UI: Record<string, { label: string; tone: Tone }> = {
  pending: { label: '待解析', tone: 'info' },
  parsed: { label: '已解析', tone: 'ok' },
  failed: { label: '解析失败', tone: 'danger' },
}

const PARSE_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待解析' },
  { value: 'parsed', label: '已解析' },
  { value: 'failed', label: '解析失败' },
]

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
        return <StatusTag tone={ui.tone} label={ui.label} />
      },
    },
    {
      title: '统计记录', dataIndex: 'stats_record_id', key: 'stats_record_id', width: 120,
      render: (id: string) => id ? <StatusTag tone="ok" label="已创建" /> : '-',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 150,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD HH:mm') : '-',
    },
  ], [])

  return (
    <div style={{ padding: '0 0 32px' }}>
      <PageHeader
        breadcrumb={['安全管理', '应急管理']}
        title="应急管理"
        description="应急演练计划、执行记录与归档台账"
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* ── 统计行（Tab 内） ── */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="收录总数" value={stats?.total ?? '—'} sub="演练计划附件收录" />
          <StatCard label="已解析" value={stats?.parsed ?? '—'} tone="ok" />
          <StatCard label="待解析" value={stats?.pending ?? '—'} tone="info" />
          <StatCard label="解析失败" value={stats?.failed ?? '—'} tone="danger" />
        </div>

        {/* ── 收录记录台账 ── */}
        <SectionCard
          title="收录记录"
          description="上传演练计划附件到飞书「演练计划收录」表，平台自动解析并创建统计记录"
        >
          <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <Select value={parseStatus} onChange={(v) => { setParseStatus(v); setPage(1); loadList(1, pageSize) }}
              options={PARSE_STATUS_FILTER} style={{ width: 140 }} placeholder="解析状态" allowClear />
          </div>

          <Table<CollectionRecord>
            columns={columns} dataSource={rows} rowKey="id"
            loading={loading} scroll={{ x: 900 }}
            locale={{ emptyText: (
              <EmptyGuide compact title="暂无收录记录" description="请在飞书「演练计划收录」表中上传附件" />
            ) }}
            pagination={{
              current: page, pageSize, total, showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, ps) => { setPage(p); setPageSize(ps); loadList(p, ps) },
            }}
            size="middle"
          />
        </SectionCard>
      </div>
    </div>
  )
}
