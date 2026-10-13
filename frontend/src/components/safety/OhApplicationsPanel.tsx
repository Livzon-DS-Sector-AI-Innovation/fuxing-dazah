'use client'

// 转岗离岗申请 Panel（OhApplicationsPanel）— 对标 CertWarningPanel 形态
// StatCard 统计行（总数/审批中/已通过/需体检，取 getOhApplicationStats）→ SectionCard 台账（筛选 + Table）
// 注：后端 list 仅支持 status/transfer_type/keyword；「是否需体检」Select 无后端参数
//     → 在当前页行内客户端过滤（已记录待后端增强）。

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Input,
  Select,
  Table,
  Tooltip,
} from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { getOhApplicationStats, getOhApplications } from '@/actions/safety'
import type { OhApplicationStats, OhExamApplication } from '@/types/safety'
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import {
  OH_APPLICATION_STATUS_FILTER,
  OH_APPLICATION_STATUS_UI,
  OH_NEEDS_EXAM_UI,
  OH_TRANSFER_TYPE_FILTER,
  OH_TRANSFER_TYPE_UI,
  UI,
} from './ohConstants'
import { linkPrimary, monoFont } from './shared-styles'
import OhApplicationDrawer from './OhApplicationDrawer'

/** 申请状态 → ui-kit 语义 tone */
const APPLY_STATUS_TONE: Record<string, Tone> = {
  '已通过': 'ok',
  '审批中': 'info',
  '已拒绝': 'danger',
  '已取消': 'default',
  '已终止': 'default',
  '已撤回': 'default',
  '已删除': 'default',
}

/** 转岗/离岗类型 → ui-kit 语义 tone */
const TRANSFER_TYPE_TONE: Record<string, Tone> = {
  transfer: 'warn',
  post_employment: 'default',
}

/** 是否需体检 → ui-kit 语义 tone */
const NEEDS_EXAM_TONE: Record<string, Tone> = {
  true: 'warn',
  false: 'ok',
  unknown: 'default',
}

function Pill({ status, map, toneMap }: {
  status?: string
  map: Record<string, { label: string; color: string; bg: string }>
  toneMap: Record<string, Tone>
}) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <StatusTag tone={toneMap[status] ?? 'default'} label={ui.label} />
}

function NeedsExamPill({ needsExam }: { needsExam?: boolean | null }) {
  const key = needsExam === undefined || needsExam === null ? 'unknown' : needsExam ? 'true' : 'false'
  return <StatusTag tone={NEEDS_EXAM_TONE[key]} label={OH_NEEDS_EXAM_UI[key].label} />
}

export default function OhApplicationsPanel() {
  const { message } = App.useApp()

  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<string | undefined>()
  const [transferType, setTransferType] = useState<string | undefined>()
  const [needsExamFilter, setNeedsExamFilter] = useState<string | undefined>()

  const [rows, setRows] = useState<OhExamApplication[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<OhApplicationStats | null>(null)

  const [detailApp, setDetailApp] = useState<OhExamApplication | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  const loadList = useCallback(async (p: number, ps: number, kw?: string) => {
    setLoading(true)
    try {
      const res = await getOhApplications({
        page: p, page_size: ps,
        status: status || undefined,
        transfer_type: transferType || undefined,
        keyword: (kw ?? keyword).trim() || undefined,
      })
      if (res.code === 200 && res.data) {
        setRows(res.data)
        setTotal(res.meta?.total ?? 0)
      } else {
        message.error(res.message || '查询失败')
      }
    } finally {
      setLoading(false)
    }
  }, [status, transferType, keyword, message])

  const loadStats = useCallback(async () => {
    try {
      const res = await getOhApplicationStats()
      if (res.code === 200 && res.data) setStats(res.data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadList(1, pageSize); loadStats() }, []) // eslint-disable-line

  const handleSearch = () => { setPage(1); loadList(1, pageSize) }

  const visibleRows = useMemo(() => {
    if (!needsExamFilter) return rows
    const target = needsExamFilter === 'true'
    return rows.filter((r) => r.needs_exam === target)
  }, [rows, needsExamFilter])

  const columns: ColumnsType<OhExamApplication> = useMemo(() => [
    {
      title: '申请编号', dataIndex: 'application_no', key: 'application_no', width: 150,
      render: (text: string, record: OhExamApplication) => (
        <span style={{ ...linkPrimary, cursor: 'pointer', fontWeight: 600 }}
          onClick={() => { setDetailApp(record); setDetailOpen(true) }}>
          <span style={monoFont}>{text || '(未填写)'}</span>
        </span>
      ),
    },
    { title: '姓名', dataIndex: 'employee_name', key: 'employee_name', width: 90, render: (v: string) => v || '-' },
    { title: '原部门', dataIndex: 'department', key: 'department', width: 120, ellipsis: true, render: (v: string) => v || '-' },
    { title: '原岗位', dataIndex: 'position', key: 'position', width: 110, ellipsis: true, render: (v: string) => v || '-' },
    {
      title: '转入部门', key: 'target_dept', width: 120, ellipsis: true,
      render: (_: unknown, r: OhExamApplication) =>
        r.transfer_type === 'transfer'
          ? (r.new_department || '-')
          : <span style={{ color: UI.muted }}>-</span>,
    },
    {
      title: '转入岗位', key: 'target_pos', width: 110, ellipsis: true,
      render: (_: unknown, r: OhExamApplication) =>
        r.transfer_type === 'transfer'
          ? (r.new_position || '-')
          : <span style={{ color: UI.muted }}>-</span>,
    },
    {
      title: '转岗/离岗日期', key: 'target_date', width: 120,
      render: (_: unknown, r: OhExamApplication) => {
        const d = r.transfer_type === 'transfer' ? r.transfer_date : r.leave_date
        return d ? dayjs(d).format('YYYY-MM-DD') : '-'
      },
    },
    {
      title: '状态', dataIndex: 'apply_status', key: 'apply_status', width: 90,
      render: (v: string) => <Pill status={v} map={OH_APPLICATION_STATUS_UI} toneMap={APPLY_STATUS_TONE} />,
    },
    {
      title: '是否需体检', dataIndex: 'needs_exam', key: 'needs_exam', width: 100,
      render: (v: boolean | null | undefined) => <NeedsExamPill needsExam={v} />,
    },
    {
      title: '类型', dataIndex: 'transfer_type', key: 'transfer_type', width: 90,
      render: (v: string) => <Pill status={v} map={OH_TRANSFER_TYPE_UI} toneMap={TRANSFER_TYPE_TONE} />,
    },
  ], []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-4 pb-8">
      {/* ── 统计行（server action stats） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="申请总数" value={stats?.total ?? '-'} sub="转岗/离岗体检申请" />
        <StatCard label="审批中" value={stats?.by_status?.['审批中'] ?? 0} sub="by_status 审批中" />
        <StatCard label="已通过" value={stats?.by_status?.['已通过'] ?? 0} sub="by_status 已通过" />
        <StatCard label="需体检" value={stats?.needs_exam ?? '-'} sub="差异分析判定需体检" />
      </div>

      <SectionCard
        title="转岗离岗申请"
        description={`转岗/离岗体检申请台账（共 ${total} 条）`}
      >
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Input allowClear placeholder="申请编号/姓名" value={keyword}
            onChange={(e) => setKeyword(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 170 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Select
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); loadList(1, pageSize) }}
            options={OH_APPLICATION_STATUS_FILTER}
            style={{ width: 130 }} allowClear
          />
          <Select
            value={transferType}
            onChange={(v) => { setTransferType(v); setPage(1); loadList(1, pageSize) }}
            options={OH_TRANSFER_TYPE_FILTER}
            style={{ width: 130 }} allowClear
          />
          <Select
            value={needsExamFilter}
            onChange={(v) => { setNeedsExamFilter(v); setPage(1) }}
            options={[
              { value: '', label: '全部' },
              { value: 'true', label: '需要体检' },
              { value: 'false', label: '无需体检' },
            ]}
            style={{ width: 130 }} allowClear
          />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={handleSearch} size="small" /></Tooltip>
        </div>

        <Table<OhExamApplication>
          columns={columns}
          dataSource={visibleRows}
          rowKey="id"
          loading={loading}
          size="middle"
          scroll={{ x: 1220 }}
          locale={{ emptyText: <EmptyGuide compact title="暂无转岗离岗申请" description="调整筛选条件后点击右侧刷新按钮应用" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); loadList(p, ps) },
          }}
        />
      </SectionCard>

      <OhApplicationDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        application={detailApp}
        onRefresh={() => loadList(page, pageSize)}
      />
    </div>
  )
}
