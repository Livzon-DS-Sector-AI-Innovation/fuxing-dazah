'use client'

// 异常随访 Panel（OhFollowupsPanel）— 对标 MsdsPanel
// KPI（总数/open/followed/逾期，由列表派生——后端无 stats 端点；逾期 = expired 或 open 且 followup_date < today）
// 筛选：状态/类别（服务端）+ 随访类型/keyword（后端 list 无对应参数 → 当前页行内客户端过滤）
// 默认按 followup_date 升序（due_order=true，到期优先）。
// 操作：处置（OhFollowupModal）/ 关闭（Popconfirm + action_taken 必填）。

import { useMemo, useState } from 'react'
import {
  App,
  Button,
  Empty,
  Input,
  Popconfirm,
  Select,
  Table,
  Tooltip,
} from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchOhFollowups } from '@/lib/api/safety/occupational-health'
import { closeOhFollowup } from '@/actions/safety'
import type { OhFollowup } from '@/types/safety'
import {
  CARD_STYLE,
  OH_FOLLOWUP_STATUS_FILTER,
  OH_FOLLOWUP_STATUS_UI,
  OH_FOLLOWUP_TYPE_FILTER,
  OH_FOLLOWUP_TYPE_UI,
  OH_INDICATOR_CATEGORY_FILTER,
  OH_INDICATOR_CATEGORY_UI,
  T,
  UI,
} from './ohConstants'
import { linkDanger, linkPrimary } from './shared-styles'
import OhFollowupModal from './OhFollowupModal'

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

function Pill({ status, map }: { status?: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

const MAX_FETCH = 200

export default function OhFollowupsPanel() {
  const { message } = App.useApp()

  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<string | undefined>()
  const [category, setCategory] = useState<string | undefined>()
  const [followupType, setFollowupType] = useState<string | undefined>()

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [disposeTarget, setDisposeTarget] = useState<OhFollowup | null>(null)
  const [disposeOpen, setDisposeOpen] = useState(false)
  const [closeText, setCloseText] = useState('')

  const queryClient = useQueryClient()

  // KPI 派生查询（后端无 stats 端点；一次性拉 200 条）
  const kpiQuery = useQuery({
    queryKey: ['oh-followups-kpi'],
    queryFn: () => fetchOhFollowups({ page: 1, page_size: MAX_FETCH, due_order: true }),
  })
  const kpi = useMemo(() => {
    const items = kpiQuery.data?.items ?? []
    const today = dayjs().startOf('day')
    return {
      total: kpiQuery.data?.total ?? items.length,
      open: items.filter((f) => f.status === 'open').length,
      followed: items.filter((f) => f.status === 'followed').length,
      overdue: items.filter((f) =>
        f.status === 'expired' ||
        (f.status === 'open' && !!f.followup_date && dayjs(f.followup_date).isBefore(today))
      ).length,
    }
  }, [kpiQuery.data])

  // 列表 query（status/category 为服务端筛选）
  const { data: listData, isLoading } = useQuery({
    queryKey: ['oh-followups', { page, pageSize, status, category }],
    queryFn: () => fetchOhFollowups({
      page, page_size: pageSize,
      status: status || undefined,
      category: category || undefined,
      due_order: true,
    }),
  })

  const rows = useMemo(() => listData?.items ?? [], [listData?.items])
  const total = listData?.total ?? 0

  const visibleRows = useMemo(() => {
    let list = rows
    const kw = keyword.trim().toLowerCase()
    if (kw) {
      list = list.filter((f) =>
        (f.person_name ?? '').toLowerCase().includes(kw) ||
        (f.indicator_name ?? '').toLowerCase().includes(kw)
      )
    }
    if (followupType) {
      list = list.filter((f) => f.followup_type === followupType)
    }
    return list
  }, [rows, keyword, followupType])

  const isOverdue = (f: OhFollowup): boolean =>
    f.status === 'expired' ||
    (f.status === 'open' && !!f.followup_date && dayjs(f.followup_date).isBefore(dayjs().startOf('day')))

  const handleClose = async (f: OhFollowup) => {
    if (!closeText.trim()) {
      message.warning('关闭随访需填写处置措施（action_taken）')
      return
    }
    try {
      const res = await closeOhFollowup(f.id, closeText.trim())
      if (res.code === 200) {
        message.success('随访已关闭')
        setCloseText('')
        queryClient.invalidateQueries({ queryKey: ['oh-followups'] })
        queryClient.invalidateQueries({ queryKey: ['oh-followups-kpi'] })
      } else {
        message.error(res.message || '关闭失败')
      }
    } finally {
      /* noop */
    }
  }

  const columns: ColumnsType<OhFollowup> = useMemo(() => [
    { title: '人员姓名', dataIndex: 'person_name', key: 'person_name', width: 110, render: (v: string) => v || '-' },
    {
      title: '异常指标 + 数值', key: 'indicator', width: 200,
      render: (_: unknown, r: OhFollowup) => (
        <span style={{ fontSize: 13 }}>
          <b>{r.indicator_name || '-'}</b>
          {r.indicator_value ? <span style={{ color: T.warning, marginLeft: 6 }}>{r.indicator_value}</span> : null}
        </span>
      ),
    },
    { title: '类别', dataIndex: 'category', key: 'category', width: 80, render: (v: string) => <Pill status={v} map={OH_INDICATOR_CATEGORY_UI} /> },
    { title: '随访类型', dataIndex: 'followup_type', key: 'followup_type', width: 100, render: (v: string) => <Pill status={v} map={OH_FOLLOWUP_TYPE_UI} /> },
    {
      title: '建议复查日期', dataIndex: 'followup_date', key: 'followup_date', width: 120,
      render: (v: string, r: OhFollowup) => {
        if (!v) return '-'
        return isOverdue(r)
          ? <span style={{ color: T.error, fontWeight: 700, fontSize: 13 }}>{dayjs(v).format('YYYY-MM-DD')}</span>
          : <span style={{ fontSize: 13 }}>{dayjs(v).format('YYYY-MM-DD')}</span>
      },
    },
    { title: '责任人', dataIndex: 'responsible', key: 'responsible', width: 90, render: (v: string) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (v: string) => <Pill status={v} map={OH_FOLLOWUP_STATUS_UI} /> },
    {
      title: '来源', dataIndex: 'source', key: 'source', width: 100,
      render: (v: string) => (
        v === 'ai'
          ? <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 4, color: T.primary, background: T.lavender, fontWeight: 600 }}>AI 自动</span>
          : <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 4, color: T.steel, background: T.gray, fontWeight: 600 }}>人工补录</span>
      ),
    },
    {
      title: '操作', key: 'actions', width: 110, fixed: 'right',
      render: (_: unknown, r: OhFollowup) => (
        <span style={{ display: 'inline-flex', gap: 10 }}>
          <span role="button" style={{ ...linkPrimary, cursor: 'pointer' }}
            onClick={() => { setDisposeTarget(r); setDisposeOpen(true) }}>
            处置
          </span>
          {r.status !== 'closed' && (
            <Popconfirm
              title="关闭随访"
              description={<Input.TextArea rows={2} placeholder="处置措施（必填）" value={closeText} onChange={(e) => setCloseText(e.target.value)} />}
              okText="确认关闭" cancelText="取消" okButtonProps={{ danger: true }}
              onConfirm={() => handleClose(r)}
              onOpenChange={(open) => { if (open) setCloseText('') }}
            >
              <span role="button" style={{ ...linkDanger, cursor: 'pointer' }}>关闭</span>
            </Popconfirm>
          )}
        </span>
      ),
    },
  ], [closeText]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="随访总数" value={String(kpi.total ?? '-')} bg={T.lavender} valueColor={T.primary} caption="异常随访闭环" />
        <KpiCard label="待随访" value={String(kpi.open)} bg={T.peach} valueColor={T.warning} caption="open 待处置" />
        <KpiCard label="已随访" value={String(kpi.followed)} bg={T.sky} valueColor="#005bab" caption="已处置待闭环" />
        <KpiCard label="已逾期" value={String(kpi.overdue)} bg={T.rose} valueColor={T.error} caption="超期未关闭" />
      </div>

      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Input allowClear placeholder="人员/指标名" value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 170 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Select
            value={status}
            onChange={(v) => { setStatus(v); setPage(1) }}
            options={OH_FOLLOWUP_STATUS_FILTER}
            style={{ width: 140 }} allowClear
          />
          <Select
            value={category}
            onChange={(v) => { setCategory(v); setPage(1) }}
            options={OH_INDICATOR_CATEGORY_FILTER}
            style={{ width: 130 }} allowClear
          />
          <Select
            value={followupType}
            onChange={(v) => { setFollowupType(v); setPage(1) }}
            options={OH_FOLLOWUP_TYPE_FILTER}
            style={{ width: 130 }} allowClear
          />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['oh-followups'] })
            queryClient.invalidateQueries({ queryKey: ['oh-followups-kpi'] })
          }} size="small" /></Tooltip>
        </div>

        <Table<OhFollowup>
          columns={columns}
          dataSource={visibleRows}
          rowKey="id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 1240 }}
          locale={{ emptyText: <Empty description="暂无异常随访" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </div>

      <OhFollowupModal
        open={disposeOpen}
        onClose={() => setDisposeOpen(false)}
        followup={disposeTarget}
        onSaved={() => {
          setDisposeOpen(false)
          queryClient.invalidateQueries({ queryKey: ['oh-followups'] })
          queryClient.invalidateQueries({ queryKey: ['oh-followups-kpi'] })
        }}
      />
    </div>
  )
}
