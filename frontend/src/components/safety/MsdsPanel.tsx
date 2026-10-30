'use client'

// MSDS 台账 Panel（MsdsPanel）— 对标 CertWarningPanel 形态
// StatCard 统计行（stats 端点）→ SectionCard MSDS 台账（筛选 + Table + 附件下载）。

import { useMemo, useState } from 'react'
import {
  Button,
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
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import MsdsDetailDrawer from './MsdsDetailDrawer'
import {
  ARCHIVE_STATUS_UI,
  REVIEW_STATUS_UI,
  TYPO_REVIEW_STATUS_UI,
  T,
  UI,
} from './msdsConstants'

/** 复核状态 → ui-kit 语义 tone */
const REVIEW_STATUS_TONE: Record<string, Tone> = {
  pending: 'default',
  approved: 'ok',
  rejected: 'danger',
}

/** 归档状态 → ui-kit 语义 tone */
const ARCHIVE_STATUS_TONE: Record<string, Tone> = {
  pending: 'default',
  archived: 'info',
}

/** 错别字审核状态 → ui-kit 语义 tone */
const TYPO_REVIEW_TONE: Record<string, Tone> = {
  未审核: 'default',
  无错别字: 'ok',
  疑似错别字: 'danger',
}

function Pill({ status, map, toneMap }: {
  status: string
  map: Record<string, { label: string; color: string; bg: string }>
  toneMap: Record<string, Tone>
}) {
  const ui = map[status]
  if (!ui) return <span>-</span>
  return <StatusTag tone={toneMap[status] ?? 'default'} label={ui.label} />
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
      render: (s: string) => <Pill status={s} map={REVIEW_STATUS_UI} toneMap={REVIEW_STATUS_TONE} />,
    },
    {
      title: '归档', dataIndex: 'archive_status', key: 'archive_status', width: 90,
      render: (s: string) => <Pill status={s} map={ARCHIVE_STATUS_UI} toneMap={ARCHIVE_STATUS_TONE} />,
    },
    {
      title: '错别字', dataIndex: 'typo_review_status', key: 'typo_review_status', width: 100,
      render: (s: string) => <Pill status={s} map={TYPO_REVIEW_STATUS_UI} toneMap={TYPO_REVIEW_TONE} />,
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
    <div className="flex flex-col gap-4 pb-8">
      {/* ── 统计行（stats 端点） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="台账总数" value={stats?.total_documents ?? '-'} sub="全部化学品 MSDS" />
        <StatCard label="已复核" value={stats?.by_review_status?.approved ?? 0} sub="复核通过" />
        <StatCard label="已归档" value={stats?.archived_documents ?? 0} sub="档案归档" />
        <StatCard label="采集记录" value={stats?.total_collections ?? '-'} sub={`失败 ${stats?.failed_collections ?? 0}`} />
      </div>

      <SectionCard
        title="MSDS 台账"
        description={`化学品安全数据说明书台账（共 ${total} 条）`}
      >
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
          locale={{ emptyText: <EmptyGuide compact title="暂无 MSDS 台账" description="供应商资料解析入库后自动生成台账" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          size="middle"
        />
      </SectionCard>

      <MsdsDetailDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={detailDoc?.name ? `${detailDoc.name} MSDS 详情` : 'MSDS 详情'}
        entry={detailDoc as MsdsDocument & undefined}
      />
    </div>
  )
}
