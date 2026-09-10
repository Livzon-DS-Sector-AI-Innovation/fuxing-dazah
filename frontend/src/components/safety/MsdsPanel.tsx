'use client'

import { useMemo, useState } from 'react'
import {
  Button,
  Empty,
  Input,
  Select,
  Table,
  Tooltip,
} from 'antd'
import { DownloadOutlined, FileTextOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import { fetchMsdsDocuments, fetchMsdsStats } from '@/lib/api/safety/msds'
import type { MsdsDocument } from '@/types/safety'
import MsdsDetailDrawer from './MsdsDetailDrawer'
import {
  ARCHIVE_STATUS_UI,
  CARD_STYLE,
  REVIEW_STATUS_UI,
  T,
  UI,
} from './msdsConstants'

function KpiCard({ label, value, caption, bg, valueColor }: {
  label: string; value: string; caption?: string; bg?: string; valueColor?: string
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: '14px 16px', background: bg ?? UI.canvas }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.stone }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: valueColor ?? UI.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: UI.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
}

function Pill({ status, map }: { status: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  const ui = map[status]
  if (!ui) return <span>-</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

export default function MsdsPanel() {
  const [name, setName] = useState('')
  const [casNo, setCasNo] = useState('')
  const [reviewStatus, setReviewStatus] = useState('')

  // 已应用筛选（点击搜索/刷新时生效）
  const [applied, setApplied] = useState<{ name: string; casNo: string; reviewStatus: string }>({ name: '', casNo: '', reviewStatus: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [detailDoc, setDetailDoc] = useState<MsdsDocument | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['msds-stats'],
    queryFn: fetchMsdsStats,
  })
  const stats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['msds', { page, pageSize, name: applied.name, casNo: applied.casNo, reviewStatus: applied.reviewStatus }],
    queryFn: () => fetchMsdsDocuments({
      page, page_size: pageSize,
      name: applied.name.trim() || undefined,
      cas_no: applied.casNo.trim() || undefined,
      review_status: applied.reviewStatus || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const handleSearch = () => {
    setApplied({ name, casNo, reviewStatus })
    setPage(1)
  }

  const columns: ColumnsType<MsdsDocument> = useMemo(() => [
    {
      title: '物质名称', dataIndex: 'name', key: 'name', width: 220, ellipsis: true,
      render: (text: string, record: MsdsDocument) => (
        <a onClick={() => { setDetailDoc(record); setDetailOpen(true) }}
           style={{ cursor: 'pointer', fontWeight: 500, color: UI.ink }}>
          {text || '(未填写)'}
        </a>
      ),
    },
    { title: 'CAS号', dataIndex: 'cas_no', key: 'cas_no', width: 110 },
    { title: 'UN编号', dataIndex: 'un_no', key: 'un_no', width: 100 },
    {
      title: '复核', dataIndex: 'review_status', key: 'review_status', width: 90,
      render: (s: string) => <Pill status={s} map={REVIEW_STATUS_UI} />,
    },
    {
      title: '归档', dataIndex: 'archive_status', key: 'archive_status', width: 90,
      render: (s: string) => <Pill status={s} map={ARCHIVE_STATUS_UI} />,
    },
    {
      title: '日期', dataIndex: 'source_date', key: 'source_date', width: 110,
      render: (d: string) => (d ? dayjs(d).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '标准文档', key: 'attachment', width: 120,
      render: (_: unknown, record: MsdsDocument) =>
        record.msds_attachment_path ? (
          <Button size="small" type="text" icon={<DownloadOutlined />}
            onClick={() =>
              window.open(`/api/v1/safety/files/${encodeURIComponent(record.msds_attachment_path!)}`, '_blank')
            }
            style={{ color: T.primary }}>下载</Button>
        ) : record.msds_attachment?.length ? (
          <span style={{ color: UI.muted, fontSize: 12 }}>已归档至飞书</span>
        ) : <span style={{ color: UI.muted, fontSize: 12 }}>无</span>,
    },
    {
      title: '操作', key: 'actions', width: 70, fixed: 'right',
      render: (_: unknown, record: MsdsDocument) => (
        <Button size="small" type="text" icon={<FileTextOutlined />}
          onClick={() => { setDetailDoc(record); setDetailOpen(true) }} />
      ),
    },
  ], [])

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="台账总数" value={String(stats?.total_documents ?? '-')} bg={T.lavender} valueColor={T.primary} caption="全部化学品 MSDS" />
        <KpiCard label="已复核" value={String(stats?.by_review_status?.approved ?? 0)} bg={T.mint} valueColor={T.success} caption="复核通过" />
        <KpiCard label="已归档" value={String(stats?.archived_documents ?? 0)} bg={T.sky} valueColor="#005bab" caption="档案归档" />
        <KpiCard label="采集记录" value={String(stats?.total_collections ?? '-')} bg={T.peach} valueColor={T.warning} caption={`失败 ${stats?.failed_collections ?? 0}`} />
      </div>

      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Input allowClear placeholder="物质名称" value={name}
            onChange={(e) => setName(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 180 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Input allowClear placeholder="CAS号" value={casNo}
            onChange={(e) => setCasNo(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 150 }} />
          <Select value={reviewStatus} onChange={(v) => setReviewStatus(v)}
            options={[
              { value: '', label: '全部复核状态' },
              { value: 'pending', label: '待复核' },
              { value: 'approved', label: '已复核' },
              { value: 'rejected', label: '已驳回' },
            ]} style={{ width: 130 }} allowClear />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={handleSearch} size="small" /></Tooltip>
        </div>

        <Table<MsdsDocument>
          columns={columns} dataSource={rows} rowKey="id"
          loading={isLoading} scroll={{ x: 980 }}
          locale={{ emptyText: <Empty description="暂无 MSDS 台账" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          size="middle"
        />
      </div>

      <MsdsDetailDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={detailDoc?.name ? `${detailDoc.name} MSDS 详情` : 'MSDS 详情'}
        entry={detailDoc as MsdsDocument & undefined}
      />
    </div>
  )
}
