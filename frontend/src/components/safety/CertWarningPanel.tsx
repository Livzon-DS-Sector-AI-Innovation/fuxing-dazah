'use client'

// 人员准入与资质：证书台账 + 持证到期预警一体（三期强化）
// PageHeader → StatCard 统计行（总持证/30 内/31-60/61-90/已过期）→ SectionCard 证书台账（筛选+表）。
// 数据全部走既有 cert 端点（列表不筛 status_level 即全量台账；统计行由 summary 六档推导 30/60/90 分层）。
// 姓名筛选：后端无 person 参数（本期无新后端）——填姓名时拉取前 200 条做检索并停用服务端分页，输入框旁明示口径。
// 回填闭环入口已按 3.0 只读口径退役（换证/复审回填走飞书表格或 Agent renew_person_certificate）。

import { useMemo, useState } from 'react'
import { Button, Input, Select, Table, Tag, Tooltip } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import { fetchCertWarningSummary, fetchCertWarnings } from '@/lib/api/safety/cert-warning'
import type { CertWarningDetail } from '@/types/safety'
import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import {
  CERT_CATEGORY_FILTER,
  CERT_CATEGORY_UI,
  T,
  WARNING_LEVEL_FILTER,
  WARNING_LEVEL_UI,
} from './certWarningConstants'

/** 姓名（本页）检索时的拉取上限（后端 page_size ≤ 200） */
const NAME_SEARCH_LIMIT = 200

/** 预警状态 → ui-kit 语义色（六档） */
const LEVEL_TONE: Record<string, Tone> = {
  normal: 'ok',
  early_notice: 'info',
  to_schedule: 'warn',
  key_warning: 'warn',
  urgent: 'danger',
  overdue: 'expired',
}

function CategoryTag({ value }: { value: string }) {
  const ui = CERT_CATEGORY_UI[value]
  if (!ui) return <span>{value || '-'}</span>
  return (
    <Tag className="m-0 rounded-md" style={{ color: ui.color, background: ui.bg, fontWeight: 600 }}>
      {ui.label}
    </Tag>
  )
}

export default function CertWarningPanel() {
  const [name, setName] = useState('')
  const [status, setStatus] = useState<string | undefined>()
  const [department, setDepartment] = useState('')
  const [certCategory, setCertCategory] = useState<string | undefined>()
  const [daysWithin, setDaysWithin] = useState('')

  // 已应用筛选（点击刷新时生效，保持原交互）
  const [applied, setApplied] = useState<{
    name: string
    status?: string
    department: string
    certCategory?: string
    daysWithin: string
  }>({ name: '', department: '', daysWithin: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const applyFilters = () => {
    setApplied({ name, status, department, certCategory, daysWithin })
    setPage(1)
  }

  // 汇总 query → StatCard 统计行（30/60/90 分层由六档推导：≤30=紧急+重点；31-60=待安排；61-90=提前关注）
  const summaryQuery = useQuery({
    queryKey: ['cert-warning-summary'],
    queryFn: () => fetchCertWarningSummary(),
  })
  const stats = useMemo(() => {
    const d = summaryQuery.data
    return {
      total: d?.total ?? 0,
      within30: (d?.urgent_count ?? 0) + (d?.key_warning_count ?? 0),
      d3160: d?.to_schedule_count ?? 0,
      d6190: d?.early_notice_count ?? 0,
      overdue: d?.overdue_count ?? 0,
    }
  }, [summaryQuery.data])

  // 列表 query：姓名检索时拉前 200 条客户端过滤（停用服务端分页）
  const nameActive = applied.name.trim() !== ''
  const { data: listData, isLoading } = useQuery({
    queryKey: ['cert-warnings', {
      page: nameActive ? 1 : page,
      pageSize: nameActive ? NAME_SEARCH_LIMIT : pageSize,
      status: applied.status,
      department: applied.department,
      certCategory: applied.certCategory,
      daysWithin: applied.daysWithin,
      name: applied.name,
    }],
    queryFn: () => fetchCertWarnings({
      page: nameActive ? 1 : page,
      page_size: nameActive ? NAME_SEARCH_LIMIT : pageSize,
      status_level: applied.status,
      department: applied.department.trim() || undefined,
      cert_category: applied.certCategory,
      days_within: applied.daysWithin ? Number(applied.daysWithin) : undefined,
    }),
  })

  const allRows = listData?.items ?? []
  const kw = applied.name.trim().toLowerCase()
  const rows = nameActive
    ? allRows.filter((r) => r.person_name?.toLowerCase().includes(kw))
    : allRows
  const total = nameActive ? rows.length : listData?.total ?? 0

  const columns: ColumnsType<CertWarningDetail> = useMemo(() => [
    { title: '姓名', dataIndex: 'person_name', key: 'person_name', width: 90, render: (v: string) => v || '-' },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100, render: (v: string) => v || '-' },
    {
      title: '证件类型', dataIndex: 'cert_category', key: 'cert_category', width: 110,
      render: (v: string) => <CategoryTag value={v} />,
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
      title: '预警状态', dataIndex: 'status_level', key: 'status_level', width: 100,
      render: (v: string) =>
        v ? (
          <StatusTag tone={LEVEL_TONE[v] ?? 'default'} label={WARNING_LEVEL_UI[v]?.label ?? v} />
        ) : (
          <span>-</span>
        ),
    },
    { title: '建议措施', dataIndex: 'suggestion', key: 'suggestion', width: 160, render: (v: string) => v || '-' },
  ], [])

  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '人员准入与资质']}
        title="人员准入与资质"
        description="证书台账与持证到期预警：准入资质底数、30/60/90 天到期分层与已逾期风险"
      />

      {/* ── 统计行（summary 六档推导） ── */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard
          label="总持证数"
          value={stats.total}
          sub="全部在册证书"
          loading={summaryQuery.isLoading}
        />
        <StatCard
          label="30 天内到期"
          value={stats.within30}
          tone={stats.within30 > 0 ? 'warn' : 'default'}
          sub="含 0-7 紧急 / 8-30 重点"
        />
        <StatCard label="31-60 天到期" value={stats.d3160} sub="待安排复审" />
        <StatCard label="61-90 天到期" value={stats.d6190} sub="提前关注" />
        <StatCard
          label="已过期"
          value={stats.overdue}
          tone={stats.overdue > 0 ? 'danger' : 'default'}
          sub="复审/换证超期"
        />
      </div>

      {/* ── 证书台账（默认全量；筛选后即预警明细视图，列与回填交互沿用既有形态） ── */}
      <SectionCard
        title="证书台账"
        description={
          nameActive
            ? `姓名检索：在最近 ${NAME_SEARCH_LIMIT} 条内命中 ${rows.length} 条（后端暂无姓名参数，服务端分页已停用）`
            : `全量证书台账（共 ${total} 条）；按预警状态筛选即为持证到期预警明细`
        }
      >
        <div className="mb-4 flex flex-wrap items-center gap-2.5">
          <Input
            allowClear
            placeholder="姓名（本页检索）"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: 150 }}
            prefix={<SearchOutlined style={{ color: 'var(--color-stone)' }} />}
            onPressEnter={applyFilters}
            data-testid="cert-name-input"
          />
          <Select
            value={status}
            onChange={(v) => { setStatus(v); setPage(1) }}
            options={WARNING_LEVEL_FILTER}
            style={{ width: 140 }} allowClear placeholder="预警状态"
          />
          <Input allowClear placeholder="部门" value={department}
            onChange={(e) => setDepartment(e.target.value)}
            style={{ width: 130 }} prefix={<SearchOutlined style={{ color: 'var(--color-stone)' }} />} />
          <Select
            value={certCategory}
            onChange={(v) => { setCertCategory(v); setPage(1) }}
            options={CERT_CATEGORY_FILTER}
            style={{ width: 130 }} allowClear placeholder="证件类型"
          />
          <Input allowClear placeholder="剩余天数 ≤" value={daysWithin}
            onChange={(e) => setDaysWithin(e.target.value)}
            style={{ width: 130 }} />
          <Tooltip title="应用筛选">
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
          locale={{
            emptyText: (
              <EmptyGuide
                compact
                title="暂无符合条件的证书"
                description="调整筛选条件后点击右侧刷新按钮应用"
              />
            ),
          }}
          pagination={
            nameActive
              ? false
              : {
                  current: page, pageSize, total, showSizeChanger: true,
                  showTotal: (t) => `共 ${t} 条`,
                  onChange: (p, ps) => { setApplied({ name, status, department, certCategory, daysWithin }); setPage(p); setPageSize(ps) },
                }
          }
        />
      </SectionCard>
    </div>
  )
}
