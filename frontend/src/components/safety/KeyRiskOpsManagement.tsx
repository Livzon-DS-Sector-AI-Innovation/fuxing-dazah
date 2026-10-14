'use client'

// 风险作业报备 — ui-kit 视觉（PageHeader / StatCard / SectionCard / StatusTag / EmptyGuide）
// 状态标签统一 ui-kit StatusTag（本地 ApplyStatusTag 已删）；取数与筛选行为不变。

import { useState } from 'react'
import {
  App, Button, DatePicker, Input, Select, Space, Table, Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  ExportOutlined, EyeOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { exportKeyRiskOpsReports } from '@/actions/safety'
import { downloadBase64Excel } from '@/actions/safety/_utils'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchKeyRiskOperationReports, fetchKeyRiskOperationStats } from '@/lib/api/safety/key-risk-operation'
import type { KeyRiskOperationReport } from '@/types/safety'
import { KEY_RISK_APPLY_STATUS_CONFIG, KEY_RISK_APPLY_STATUS_OPTIONS } from '@/types/safety'
import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import KeyRiskOpsDetail from './KeyRiskOpsDetail'

const { Text } = Typography
const { RangePicker } = DatePicker

// ── DESIGN tokens（对齐 SpecialOpsManagement）──

const UI = {
  ink: '#1a1a1a',
  slate: '#5d5b54',
  steel: '#787671',
  stone: '#a4a097',
} as const

const MONO_FONT = 'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace'

/** 申请状态 → ui-kit 语义 tone */
const APPLY_STATUS_TONE: Record<string, Tone> = {
  '已通过': 'ok',
  '审批中': 'info',
  '已拒绝': 'danger',
  '已取消': 'default',
  '已终止': 'expired',
  '已撤回': 'default',
}

function ApplyStatusTag({ status }: { status?: string }) {
  if (!status) return <Text style={{ color: UI.stone }}>—</Text>
  return <StatusTag tone={APPLY_STATUS_TONE[status] ?? 'default'} label={KEY_RISK_APPLY_STATUS_CONFIG[status]?.label ?? status} />
}

export default function KeyRiskOpsManagement() {
  const { message } = App.useApp()

  // ── 列表 ──
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // ── 筛选 ──
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [dept, setDept] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null)
  const [keyword, setKeyword] = useState('')
  const [submittedKeyword, setSubmittedKeyword] = useState('')

  // ── 操作 ──
  const [exporting, setExporting] = useState(false)

  // ── 详情 ──
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailItem, setDetailItem] = useState<KeyRiskOperationReport | null>(null)

  const queryClient = useQueryClient()

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['key-risk-ops'] })
    queryClient.invalidateQueries({ queryKey: ['key-risk-ops-stats'] })
  }

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['key-risk-ops-stats'],
    queryFn: fetchKeyRiskOperationStats,
  })
  const stats = statsQuery.data ?? null

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['key-risk-ops', {
      page, pageSize,
      statusFilter, dept,
      dateFrom: dateRange?.[0]?.format('YYYY-MM-DD'),
      dateTo: dateRange?.[1]?.format('YYYY-MM-DD'),
      submittedKeyword,
    }],
    queryFn: () => fetchKeyRiskOperationReports({
      page, page_size: pageSize,
      apply_status: statusFilter || undefined,
      department: dept,
      date_from: dateRange?.[0]?.format('YYYY-MM-DD'),
      date_to: dateRange?.[1]?.format('YYYY-MM-DD'),
      keyword: submittedKeyword.trim() || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const handleExport = async () => {
    setExporting(true)
    try {
      const body: Record<string, unknown> = {
        apply_status: statusFilter || undefined,
        department: dept,
        date_from: dateRange?.[0]?.format('YYYY-MM-DD'),
        date_to: dateRange?.[1]?.format('YYYY-MM-DD'),
        keyword: keyword.trim() || undefined,
      }
      Object.keys(body).forEach(k => { if (body[k] === undefined || body[k] === null || body[k] === '') delete body[k] })
      const { blob } = await exportKeyRiskOpsReports(body)
      downloadBase64Excel(blob, `关键风险作业台账_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`)
      message.success('导出成功')
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  // ── 部门选项（从当前页数据提取）──
  const deptOptions = Array.from(new Set(rows.map(r => r.department).filter(Boolean) as string[]))
    .sort().map(d => ({ value: d, label: d }))

  // ── 表格 ──
  const columns: ColumnsType<KeyRiskOperationReport> = [
    {
      title: '申请编号', dataIndex: 'report_no', width: 130,
      render: (v: string, r) => (
        <a onClick={() => { setDetailItem(r); setDetailOpen(true) }}
          style={{ fontFamily: MONO_FONT, fontSize: 13, color: UI.ink, cursor: 'pointer' }}>{v}</a>
      ),
    },
    { title: '申请状态', dataIndex: 'apply_status', width: 90, render: (v: string) => <ApplyStatusTag status={v} /> },
    { title: '部门', dataIndex: 'department', width: 90, ellipsis: true, render: (v: string) => <span style={{ fontSize: 12, color: UI.slate }}>{v ?? '—'}</span> },
    { title: '区域', dataIndex: 'area', width: 130, ellipsis: true, render: (v: string) => <span style={{ fontSize: 13 }}>{v ?? '—'}</span> },
    { title: '作业内容', dataIndex: 'operation_content', width: 130, ellipsis: true, render: (v: string | null) => <span style={{ fontSize: 13 }}>{v ?? '—'}</span> },
    {
      title: '作业时间', dataIndex: 'start_time', width: 120,
      render: (v: string, r) => {
        const start = v ? dayjs(v).format('MM/DD HH:mm') : ''
        const end = r.end_time ? dayjs(r.end_time).format('HH:mm') : ''
        return <span style={{ fontSize: 12, color: UI.slate, fontVariantNumeric: 'tabular-nums' }}>{start}{end ? ` ~ ${end}` : ''}</span>
      },
    },
    { title: '时长', dataIndex: 'duration_hours', width: 60, render: (v: number | null) => <span style={{ fontSize: 12, color: UI.steel }}>{v != null ? `${v}h` : '—'}</span> },
    { title: '监护人', dataIndex: 'guardian', width: 90, ellipsis: true, render: (v: string) => <span style={{ fontSize: 12, color: UI.slate }}>{v ?? '—'}</span> },
    {
      title: '', key: 'action', width: 48, fixed: 'right' as const,
      render: (_, r) => (
        <Button type="text" size="small" icon={<EyeOutlined style={{ color: UI.steel }} />}
          onClick={() => { setDetailItem(r); setDetailOpen(true) }} />
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      {/* ── 页头 ── */}
      <PageHeader
        breadcrumb={['安全管理', '风险作业报备']}
        title="风险作业报备"
        description="关键风险作业报备记录与审批结果查询（审批在飞书完成 · 平台只读展示）"
        actions={
          <>
            <Button icon={<ReloadOutlined />} onClick={refresh} title="刷新" />
            <Button icon={<ExportOutlined />} loading={exporting} onClick={handleExport}>导出</Button>
          </>
        }
      />

      {/* ── 统计行（stats 端点） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="今日已通过" value={stats?.today_approved ?? 0} sub="作业开始时间落在今天且已通过" />
        <StatCard label="审批中" value={stats?.in_progress ?? 0} sub="飞书审批流尚未结束" />
        <StatCard label="本月已通过" value={stats?.month_approved ?? 0} sub="本月已通过的关键风险作业" />
        <StatCard label="累计记录" value={stats?.total ?? 0} sub="平台累计同步记录" />
      </div>

      {/* ── 报备台账（筛选 + 表格） ── */}
      <SectionCard
        title="报备台账"
        description={`关键风险作业报备记录（共 ${total} 条）`}
      >
        <div style={{ marginBottom: 16 }}>
          <Space wrap size="middle">
            <Select
              placeholder="申请状态" allowClear style={{ width: 120, borderRadius: 8 }}
              value={statusFilter || undefined}
              onChange={v => setStatusFilter(v || '')}
              options={KEY_RISK_APPLY_STATUS_OPTIONS}
            />
            <Select
              placeholder="部门" allowClear showSearch style={{ width: 150, borderRadius: 8 }}
              value={dept} onChange={setDept} options={deptOptions}
            />
            <RangePicker
              style={{ borderRadius: 8 }}
              value={dateRange}
              onChange={(v) => setDateRange(v as [dayjs.Dayjs, dayjs.Dayjs] | null)}
            />
            <Input
              placeholder="搜索编号/内容/区域/部门"
              prefix={<SearchOutlined style={{ color: UI.stone }} />}
              style={{ width: 200, borderRadius: 8 }}
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              onPressEnter={() => { setSubmittedKeyword(keyword); setPage(1) }}
              allowClear
            />
            <Button icon={<SearchOutlined />} style={{ borderRadius: 8 }} onClick={() => { setSubmittedKeyword(keyword); setPage(1) }}>查询</Button>
          </Space>
        </div>

        <Table<KeyRiskOperationReport>
          columns={columns}
          dataSource={rows}
          rowKey="id"
          loading={isLoading}
          scroll={{ x: 1000 }}
          size="middle"
          locale={{ emptyText: <EmptyGuide compact title="暂无关键风险作业记录" description="调整筛选条件后点击查询按钮应用" /> }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => <Text style={{ color: UI.steel }}>共 {t} 条</Text>,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </SectionCard>

      {/* ── 详情 ── */}
      {/* item 不在 onClose 里清：KeyRiskOpsDetail 首行 if(!item) return null，关闭瞬间卸载 Modal 会打断离场动画；打开时已整体替换 item */}
      <KeyRiskOpsDetail open={detailOpen} item={detailItem} onClose={() => setDetailOpen(false)} />
    </div>
  )
}
