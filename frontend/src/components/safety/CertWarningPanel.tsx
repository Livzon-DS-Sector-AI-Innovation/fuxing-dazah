'use client'

// 持证到期预警 Panel（CertWarningPanel）— 对标 OhFollowupsPanel
// 顶部 KPI 汇总（从 summary 获取）+ 筛选（状态/部门/证件类型/剩余天数）+ 表格 + 分页
// 操作：回填 → 打开 CertRenewDrawer

import { useMemo, useState } from 'react'
import { Button, Empty, Input, Select, Table, Tooltip } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchCertWarningSummary, fetchCertWarnings } from '@/lib/api/safety/cert-warning'
import type { CertWarningDetail } from '@/types/safety'
import {
  CERT_CATEGORY_FILTER,
  CERT_CATEGORY_UI,
  CARD_STYLE,
  T,
  UI,
  WARNING_KPI_ITEMS,
  WARNING_LEVEL_FILTER,
  WARNING_LEVEL_UI,
} from './certWarningConstants'
import { linkPrimary } from './shared-styles'
import CertRenewDrawer from './CertRenewDrawer'

function KpiCard({ label, value, caption, bg, valueColor }: {
  label: string
  value: number | string
  caption?: string
  bg?: string
  valueColor?: string
}) {
  return (
    <div style={{ ...CARD_STYLE as React.CSSProperties, flex: 1, minWidth: 0, padding: '14px 16px', background: bg ?? UI.canvas }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: UI.stone }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: valueColor ?? UI.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: UI.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
}

function Pill({ status, map }: { status?: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

export default function CertWarningPanel() {
  const [status, setStatus] = useState<string | undefined>()
  const [department, setDepartment] = useState('')
  const [certCategory, setCertCategory] = useState<string | undefined>()
  const [daysWithin, setDaysWithin] = useState('')

  // 已应用筛选（点击刷新/分页时生效，保持原交互）
  const [applied, setApplied] = useState<{ status?: string; department: string; certCategory?: string; daysWithin: string }>({ department: '', daysWithin: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [renewTarget, setRenewTarget] = useState<CertWarningDetail | null>(null)

  const queryClient = useQueryClient()

  const applyFilters = () => {
    setApplied({ status, department, certCategory, daysWithin })
  }

  // 汇总 query
  const summaryQuery = useQuery({
    queryKey: ['cert-warning-summary'],
    queryFn: () => fetchCertWarningSummary(),
  })
  const kpi = useMemo(() => {
    const d = summaryQuery.data
    if (!d) return {} as Record<string, number>
    return {
      overdue: d.overdue_count ?? 0,
      urgent: d.urgent_count ?? 0,
      key_warning: d.key_warning_count ?? 0,
      to_schedule: d.to_schedule_count ?? 0,
      early_notice: d.early_notice_count ?? 0,
      total: d.total ?? 0,
    }
  }, [summaryQuery.data])

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['cert-warnings', {
      page, pageSize,
      status: applied.status,
      department: applied.department,
      certCategory: applied.certCategory,
      daysWithin: applied.daysWithin,
    }],
    queryFn: () => fetchCertWarnings({
      page, page_size: pageSize,
      status_level: applied.status,
      department: applied.department.trim() || undefined,
      cert_category: applied.certCategory,
      days_within: applied.daysWithin ? Number(applied.daysWithin) : undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  // —— 剩余天数（客户端派生，后端仅返回非空记录）——

  const columns: ColumnsType<CertWarningDetail> = useMemo(() => [
    { title: '姓名', dataIndex: 'person_name', key: 'person_name', width: 90, render: (v: string) => v || '-' },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100, render: (v: string) => v || '-' },
    {
      title: '证件类型', dataIndex: 'cert_category', key: 'cert_category', width: 110,
      render: (v: string) => <Pill status={v} map={CERT_CATEGORY_UI} />,
    },
    { title: '项目', dataIndex: 'project', key: 'project', width: 90, render: (v: string) => v || '-' },
    { title: '当前节点', dataIndex: 'current_node', key: 'current_node', width: 110, render: (v: string) => v || '-' },
    {
      title: '截止日期', dataIndex: 'deadline', key: 'deadline', width: 110,
      render: (v: string, r: CertWarningDetail) => {
        if (!v) return '-'
        const isOverdue = (r.remaining_days ?? 0) < 0
        return <span style={{ color: isOverdue ? T.error : undefined, fontSize: 13 }}>{dayjs(v).format('YYYY-MM-DD')}</span>
      },
    },
    {
      title: '剩余天数', dataIndex: 'remaining_days', key: 'remaining_days', width: 90,
      render: (v: number) => (v != null ? <span style={{ color: v < 0 ? T.error : T.warning, fontWeight: 600, fontSize: 13 }}>{v}</span> : '-'),
    },
    {
      title: '预警状态', dataIndex: 'status_level', key: 'status_level', width: 90,
      render: (v: string) => <Pill status={v} map={WARNING_LEVEL_UI} />,
    },
    { title: '建议措施', dataIndex: 'suggestion', key: 'suggestion', width: 160, render: (v: string) => v || '-' },
    {
      title: '操作', key: 'actions', width: 80, fixed: 'right',
      render: (_: unknown, r: CertWarningDetail) => (
        <span role="button" style={{ ...linkPrimary, cursor: 'pointer' }}
          onClick={() => { setRenewTarget(r); setDrawerOpen(true) }}>
          回填
        </span>
      ),
    },
  ], [])

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 20 }}>
        {WARNING_KPI_ITEMS.map((item) => (
          <KpiCard
            key={item.label}
            label={item.label}
            value={kpi[item.field] ?? '-'}
            caption={item.caption}
            bg={item.bg}
            valueColor={item.valueColor}
          />
        ))}
      </div>

      <div style={{ ...CARD_STYLE as React.CSSProperties, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Select
            value={status}
            onChange={(v) => { setStatus(v); setPage(1) }}
            options={WARNING_LEVEL_FILTER}
            style={{ width: 140 }} allowClear placeholder="预警状态"
          />
          <Input allowClear placeholder="部门" value={department}
            onChange={(e) => setDepartment(e.target.value)}
            style={{ width: 130 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Select
            value={certCategory}
            onChange={(v) => { setCertCategory(v); setPage(1) }}
            options={CERT_CATEGORY_FILTER}
            style={{ width: 130 }} allowClear placeholder="证件类型"
          />
          <Input allowClear placeholder="剩余天数 ≤" value={daysWithin}
            onChange={(e) => setDaysWithin(e.target.value)}
            style={{ width: 130 }} />
          <Tooltip title="刷新">
            <Button icon={<ReloadOutlined />} onClick={applyFilters} size="small" />
          </Tooltip>
        </div>

        <Table<CertWarningDetail>
          columns={columns}
          dataSource={rows}
          rowKey="id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 1240 }}
          locale={{ emptyText: <Empty description="暂无持证到期记录" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { applyFilters(); setPage(p); setPageSize(ps) },
          }}
        />
      </div>

      <CertRenewDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        record={renewTarget}
        onSaved={() => {
          setDrawerOpen(false)
          queryClient.invalidateQueries({ queryKey: ['cert-warnings'] })
          queryClient.invalidateQueries({ queryKey: ['cert-warning-summary'] })
        }}
      />
    </div>
  )
}