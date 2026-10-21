'use client'

/**
 * 三台账通用 Tab（facilities-p1 票 01）——「空态即设计」。
 *
 * 三态信封（not_connected/live/degraded）+ StatCard 统计行（在用/逾期/
 * 30 天内到期/信息不全）+ 标准字段分页表。纯只读：台账在飞书多维表格维护，
 * Web 端不提供增删改（拍板口径）。列按台账类型微调（消防含换药/报废到期，
 * 特设含注册代码/检验机构/接入监控）。
 */
import { useState } from 'react'
import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { DatabaseZap, TriangleAlert } from 'lucide-react'
import { fetchFacilitiesLedger } from '@/lib/api/safety/facilities'
import type {
  FacilitiesLedgerKey,
  FacilitiesLedgerRow,
} from '@/types/safety/facilities'
import {
  EmptyGuide,
  SectionCard,
  StatCard,
  StatusTag,
} from '@/components/ui-kit'
import { OVERDUE_WARN, overdueColor } from './facilitiesConstants'

const STATUS_TAG = {
  not_connected: { label: '未接入', tone: 'default' as const },
  live: { label: '已接入', tone: 'ok' as const },
  degraded: { label: '数据降级', tone: 'warn' as const },
}

function fmtDate(value: string | null): string {
  return value ? value.slice(0, 10) : '—'
}

function fmtCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function anchorSourceLabel(row: FacilitiesLedgerRow): string {
  if (row.anchor_source === 'derived') return '推算'
  if (row.anchor_source === 'none') return '缺'
  return '直读'
}

export default function FacilitiesLedgerTab({
  ledger,
  title,
  description,
}: {
  ledger: FacilitiesLedgerKey
  title: string
  description: string
}) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const query = useQuery({
    queryKey: ['facilities-ledger', ledger, { page, pageSize }],
    queryFn: () => fetchFacilitiesLedger(ledger, { page, page_size: pageSize }),
  })
  const data = query.data
  const status = data?.status
  const summary = data?.summary
  const tag = status ? STATUS_TAG[status] : undefined
  const live = status === 'live' && summary

  const isFire = ledger === 'fire-equipment'
  const isSpecial = ledger === 'special-equipment'

  const columns: ColumnsType<FacilitiesLedgerRow> = [
    { title: '编号', dataIndex: 'equipment_no', width: 110, render: fmtCell },
    { title: '名称', dataIndex: 'name', width: 140, render: fmtCell },
    { title: '类别', dataIndex: 'category', width: 100, render: fmtCell },
    { title: '位置', dataIndex: 'location', width: 120, render: fmtCell },
    { title: '责任部门', dataIndex: 'department', width: 110, render: fmtCell },
    { title: '责任人', dataIndex: 'owner', width: 80, render: fmtCell },
    { title: '上次', dataIndex: 'last_date', width: 100, render: fmtDate },
    ...(isFire
      ? [
          { title: '换药到期', dataIndex: 'refill_due', width: 100, render: fmtDate },
          { title: '报废到期', dataIndex: 'scrap_due', width: 100, render: fmtDate },
        ]
      : []),
    ...(isSpecial
      ? [
          { title: '注册代码', dataIndex: 'register_code', width: 130, render: fmtCell },
          { title: '检验机构', dataIndex: 'agency', width: 130, render: fmtCell },
          {
            title: '接入监控',
            dataIndex: 'monitor_flag',
            width: 90,
            render: (v: boolean) => (v ? <Tag color="blue">是</Tag> : '—'),
          },
        ]
      : []),
    {
      title: '督办锚点',
      dataIndex: 'anchor',
      width: 110,
      render: (_: unknown, row: FacilitiesLedgerRow) =>
        row.anchor ? (
          <span>
            {fmtDate(row.anchor)}
            <Tag style={{ marginLeft: 4 }}>{anchorSourceLabel(row)}</Tag>
          </span>
        ) : (
          <Tag color="default">缺锚点</Tag>
        ),
    },
    {
      title: '剩余天数',
      dataIndex: 'remaining_days',
      width: 90,
      render: (v: number | null, _row: FacilitiesLedgerRow) => {
        if (v === null || v === undefined) return '—'
        if (v < 0) {
          const color = overdueColor(v)
          if (color) return <span style={{ color, fontWeight: 600 }}>逾期 {Math.abs(v)} 天</span>
        }
        if (v <= 30) return <span style={{ color: OVERDUE_WARN, fontWeight: 600 }}>{v} 天</span>
        return `${v} 天`
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (v: string | null, row: FacilitiesLedgerRow) =>
        v ?? (row.active ? '在用' : '—'),
    },
    {
      title: '记录',
      dataIndex: 'record_url',
      width: 88,
      render: (v: string | null) =>
        v ? (
          <a href={v} target="_blank" rel="noreferrer">
            打开记录
          </a>
        ) : null,
    },
  ]

  const emptyGuide = (() => {
    if (query.isError) {
      return (
        <EmptyGuide
          compact
          icon={<TriangleAlert size={28} />}
          title="数据暂时不可用"
          description="页面数据加载失败，请稍后重试或联系管理员"
        />
      )
    }
    if (status === 'not_connected') {
      return (
        <EmptyGuide
          compact
          icon={<DatabaseZap size={28} />}
          title="台账数据源未接入"
          description={`${title}的多维表格连接尚未登记（登记 app_token/table_id 后本页零改码出数）`}
        />
      )
    }
    if (status === 'degraded') {
      return (
        <EmptyGuide
          compact
          icon={<TriangleAlert size={28} />}
          title="数据源读取降级"
          description={(data?.errors ?? []).join('；') || '连接有效但读取失败，稍后自动恢复'}
        />
      )
    }
    return (
      <EmptyGuide
        compact
        title="暂无记录"
        description={`台账在飞书多维表格维护，共 ${data?.ledger.meta.total ?? 0} 条`}
      />
    )
  })()

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{title}</span>
          <span style={{ marginLeft: 10, fontSize: 12, color: '#a4a097' }}>{description}</span>
        </div>
        {tag ? <StatusTag label={tag.label} tone={tag.tone} /> : undefined}
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          label="台账总数"
          value={live ? String(summary.total) : '—'}
          tone="default"
          sub={`在用 ${live ? summary.active : '—'}`}
          loading={query.isLoading}
        />
        <StatCard
          label="校验逾期"
          value={live ? String(summary.overdue) : '—'}
          tone={live && summary.overdue > 0 ? 'danger' : 'default'}
          sub="锚点日期已过"
          loading={query.isLoading}
        />
        <StatCard
          label="30 天内到期"
          value={live ? String(summary.due_30d) : '—'}
          tone={live && summary.due_30d > 0 ? 'warn' : 'default'}
          sub="督办窗口内"
          loading={query.isLoading}
        />
        <StatCard
          label="信息不全"
          value={live ? String(summary.incomplete) : '—'}
          tone={live && summary.incomplete > 0 ? 'warn' : 'default'}
          sub="缺编号或缺锚点（推算不可得）"
          loading={query.isLoading}
        />
        <StatCard
          label="数据状态"
          value={live ? '直读' : status === 'not_connected' ? '未接入' : '降级'}
          tone={tag?.tone ?? 'default'}
          sub="飞书多维表格唯一事实源"
          loading={query.isLoading}
        />
      </div>

      <SectionCard title={`${title}台账`} description="只读直读视图；台账维护在飞书多维表格">
        <Table
          columns={columns}
          dataSource={data?.ledger.data ?? []}
          rowKey="record_id"
          size="small"
          loading={query.isLoading}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: emptyGuide }}
          pagination={{
            current: page,
            pageSize,
            total: data?.ledger.meta.total ?? 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage)
              setPageSize(nextPageSize)
            },
          }}
        />
      </SectionCard>
    </div>
  )
}
