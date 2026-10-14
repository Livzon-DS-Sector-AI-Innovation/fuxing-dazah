'use client'

import { useMemo, useState } from 'react'
import {
  Button,
  Input,
  Select,
  Table,
  Tooltip,
} from 'antd'
import {
  ReloadOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import { fetchDrillRecords, fetchDrillStats } from '@/lib/api/safety/emergency-drill'
import type { DrillRecord } from '@/types/safety'
import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import DrillDetailDrawer from './DrillDetailDrawer'
import {
  DRILL_TYPE_FILTER,
  DRILL_TYPE_UI,
  REVIEW_STATUS_FILTER,
  REVIEW_STATUS_UI,
  STAGE_FILTER,
  STAGE_UI,
  T,
} from './emergencyDrillConstants'

// ── 环节/复核状态 → ui-kit 语义 tone ──
// 环节为阶段推进（计划 info / 实施 warn / 复核 primary，对应原蓝/橙/紫配色）

const STAGE_TONE: Record<string, Tone> = { plan: 'info', execution: 'warn', review: 'primary' }
const REVIEW_STATUS_TONE: Record<string, Tone> = { 已完成: 'ok', 未完成: 'warn' }

// ── 主面板 ──

export default function EmergencyDrillPanel() {
  const [stage, setStage] = useState('')
  const [drillType, setDrillType] = useState('')
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('')
  const [keyword, setKeyword] = useState('')

  // 已应用筛选（点击查询/回车时生效）
  const [applied, setApplied] = useState<{ stage: string; drillType: string; department: string; status: string; keyword: string }>({ stage: '', drillType: '', department: '', status: '', keyword: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [detailRecord, setDetailRecord] = useState<DrillRecord | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['drill-stats'],
    queryFn: fetchDrillStats,
  })
  const stats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['drills', { page, pageSize, stage: applied.stage, drillType: applied.drillType, department: applied.department, status: applied.status, keyword: applied.keyword }],
    queryFn: () => fetchDrillRecords({
      page, page_size: pageSize,
      stage: applied.stage || undefined,
      drill_type: applied.drillType || undefined,
      department: applied.department || undefined,
      status: applied.status || undefined,
      keyword: applied.keyword.trim() || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const handleSearch = () => {
    setApplied({ stage, drillType, department, status, keyword })
    setPage(1)
  }

  const columns: ColumnsType<DrillRecord> = useMemo(() => [
    {
      title: '演练内容', dataIndex: 'drill_content', key: 'drill_content',
      ellipsis: true, width: 280,
      render: (text: string, record: DrillRecord) => (
        <a onClick={() => { setDetailRecord(record); setDetailOpen(true) }}
           style={{ cursor: 'pointer', fontWeight: 500, color: T.ink }}>
          {text || '(未填写)'}
        </a>
      ),
    },
    {
      title: '类型', dataIndex: 'drill_type', key: 'drill_type', width: 110,
      render: (t: string) => {
        const ui = DRILL_TYPE_UI[t]
        if (!ui) return t || '-'
        return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.text, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
      },
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 120 },
    {
      title: '环节', key: 'stage', width: 80,
      render: (_: unknown, record: DrillRecord) => {
        let s = 'plan'
        if (record.status) s = 'review'
        else if (record.execution_time) s = 'execution'
        return <StatusTag tone={STAGE_TONE[s] ?? 'default'} label={STAGE_UI[s].label} />
      },
    },
    {
      title: '复核', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const ui = REVIEW_STATUS_UI[s]
        if (!ui) return '-'
        return <StatusTag tone={REVIEW_STATUS_TONE[s] ?? 'default'} label={ui.label} />
      },
    },
    {
      title: '实施时间', dataIndex: 'execution_time', key: 'execution_time', width: 110,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD') : '-',
    },
    { title: '组织人', dataIndex: 'organizer', key: 'organizer', width: 100, ellipsis: true },
    {
      title: '操作', key: 'actions', width: 80, fixed: 'right',
      render: (_: unknown, record: DrillRecord) => (
        <Button size="small" type="text" icon={<FileTextOutlined />}
          onClick={() => { setDetailRecord(record); setDetailOpen(true) }} />
      ),
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
          <StatCard label="演练总数" value={stats?.total ?? '—'} sub="全部记录" />
          <StatCard label="已执行" value={stats?.executed ?? '—'} tone="info" sub="实施阶段" />
          <StatCard label="已完成" value={stats?.completed ?? '—'} tone="ok" sub="复核通过" />
          <StatCard label="待处理" value={stats?.pending ?? '—'} tone="warn" sub="未完成复核" />
        </div>

        {/* ── 演练记录台账 ── */}
        <SectionCard
          title="演练记录"
          description={`演练计划执行记录（共 ${total} 条）`}
        >
          <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            <Select value={stage} onChange={(v) => setStage(v)} options={STAGE_FILTER}
              style={{ width: 120 }} placeholder="环节" allowClear />
            <Select value={drillType} onChange={(v) => setDrillType(v)} options={DRILL_TYPE_FILTER}
              style={{ width: 140 }} placeholder="演练类型" allowClear />
            <Select value={department} onChange={(v) => setDepartment(v)}
              options={stats ? [{value: '', label: '全部部门'}, ...Object.keys(stats.by_department).map(k => ({value: k, label: k}))] : []}
              style={{ width: 140 }} placeholder="部门" allowClear showSearch
              filterOption={(input, option) => (option?.label as string)?.includes(input)} />
            <Select value={status} onChange={(v) => setStatus(v)} options={REVIEW_STATUS_FILTER}
              style={{ width: 120 }} placeholder="复核状态" allowClear />
            <Input.Search value={keyword} onChange={(e) => setKeyword(e.target.value)}
              onSearch={handleSearch} placeholder="搜索演练内容" style={{ width: 220 }} allowClear />
            <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={handleSearch} size="small" /></Tooltip>
          </div>

          <Table<DrillRecord>
            columns={columns} dataSource={rows} rowKey="id"
            loading={isLoading} scroll={{ x: 1150 }}
            locale={{ emptyText: (
              <EmptyGuide compact title="暂无演练记录" description="调整筛选条件，或等待飞书「演练计划收录」表解析生成" />
            ) }}
            pagination={{
              current: page, pageSize, total, showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, ps) => { setPage(p); setPageSize(ps) },
            }}
            size="middle"
          />
        </SectionCard>
      </div>

      <DrillDetailDrawer open={detailOpen} record={detailRecord}
        onClose={() => setDetailOpen(false)} />
    </div>
  )
}
