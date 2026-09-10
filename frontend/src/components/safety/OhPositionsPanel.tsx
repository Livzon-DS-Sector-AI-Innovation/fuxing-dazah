'use client'

// 岗位危害 Panel（OhPositionsPanel）— 只读台账
// KPI（岗位总数/已填充/未填充/涉及危害因素种数，由全量拉取派生——后端无 stats 端点）
// 筛选：部门（服务端）+ 填充状态（服务端）+ keyword（岗位/职务，后端 list 无 keyword 参数 → 客户端过滤）
// 数据量小：一次性 page_size=200 全量拉取，客户端过滤 + 客户端分页。

import { useMemo, useState } from 'react'
import {
  Button,
  Empty,
  Input,
  Select,
  Table,
  Tooltip,
} from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { fetchOhHazardFactors, fetchOhPositions } from '@/lib/api/safety/occupational-health'
import type { OhPosition } from '@/types/safety'
import {
  CARD_STYLE,
  OH_POSITION_FILL_STATUS_FILTER,
  OH_POSITION_FILL_STATUS_UI,
  T,
  UI,
} from './ohConstants'
import OhPositionDrawer from './OhPositionDrawer'

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

function Pill({ status }: { status?: string }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = OH_POSITION_FILL_STATUS_UI[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

const MAX_FETCH = 200

export default function OhPositionsPanel() {
  const [keyword, setKeyword] = useState('')
  const [department, setDepartment] = useState('')
  const [fillStatus, setFillStatus] = useState<string | undefined>()

  // 已应用筛选（部门回车 / 填充状态选中时生效）
  const [applied, setApplied] = useState<{ department: string; fillStatus?: string }>({ department: '' })

  const [detailPosition, setDetailPosition] = useState<OhPosition | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // 岗位列表（全量拉取 + 服务端筛选）
  const { data: listData, isLoading } = useQuery({
    queryKey: ['oh-positions', { department: applied.department, fillStatus: applied.fillStatus }],
    queryFn: () => fetchOhPositions({
      page: 1,
      page_size: MAX_FETCH,
      department: applied.department.trim() || undefined,
      hazard_factors_status: applied.fillStatus || undefined,
    }),
  })
  const rows = useMemo(() => listData?.items ?? [], [listData?.items])
  const total = listData?.total ?? 0

  // 危害因素 PPE 字典
  const hazardFactorsQuery = useQuery({
    queryKey: ['oh-hazard-factors'],
    queryFn: () => fetchOhHazardFactors({ page: 1, page_size: MAX_FETCH }),
  })
  const hazardFactors = hazardFactorsQuery.data ?? []

  // KPI 由全量数据派生
  const kpi = useMemo(() => {
    const filled = rows.filter((r) => r.hazard_factors_status === 'filled').length
    const empty = rows.filter((r) => r.hazard_factors_status === 'empty' || !r.hazard_factors_status).length
    const factorSet = new Set<string>()
    rows.forEach((r) => (r.hazard_factors ?? []).forEach((f) => factorSet.add(f)))
    return {
      total: total,
      filled,
      empty,
      factorCount: factorSet.size,
      fillRate: total > 0 ? Math.round(((total - empty) / total) * 100) : 0,
    }
  }, [rows, total])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return rows
    return rows.filter((r) =>
      (r.position ?? '').toLowerCase().includes(kw) ||
      (r.job_title ?? '').toLowerCase().includes(kw)
    )
  }, [rows, keyword])

  const columns: ColumnsType<OhPosition> = useMemo(() => [
    { title: '部门', dataIndex: 'department', key: 'department', width: 160, ellipsis: true, render: (v: string) => v || '-' },
    {
      title: '岗位', dataIndex: 'position', key: 'position', width: 200,
      render: (text: string, record: OhPosition) => (
        <a onClick={() => { setDetailPosition(record); setDetailOpen(true) }}
           style={{ cursor: 'pointer', fontWeight: 500, color: UI.ink }}>
          {text || '(未填写)'}
        </a>
      ),
    },
    { title: '职务', dataIndex: 'job_title', key: 'job_title', width: 140, render: (v: string) => v || '-' },
    {
      title: '危害因素', dataIndex: 'hazard_factors', key: 'hazard_factors', width: 260,
      render: (v: string[] | undefined) => {
        if (!v || v.length === 0) return <span style={{ color: UI.muted }}>-</span>
        const shown = v.slice(0, 3)
        const rest = v.slice(3)
        return (
          <span>
            {shown.map((h) => (
              <span key={h} style={{ fontSize: 12, padding: '1px 8px', borderRadius: 4, color: '#391c57', background: T.lavender, fontWeight: 500, marginRight: 4 }}>{h}</span>
            ))}
            {rest.length > 0 && (
              <Tooltip title={rest.join('、')}>
                <span style={{ fontSize: 12, color: UI.steel, cursor: 'pointer' }}>+{rest.length}</span>
              </Tooltip>
            )}
          </span>
        )
      },
    },
    {
      title: '填充状态', dataIndex: 'hazard_factors_status', key: 'hazard_factors_status', width: 100,
      render: (v: string) => <Pill status={v} />,
    },
  ], [])

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="岗位总数" value={String(kpi.total ?? '-')} bg={T.lavender} valueColor={T.primary} caption="岗位危害台账" />
        <KpiCard label="已填充危害" value={String(kpi.filled)} bg={T.mint} valueColor={T.success} caption={`填充率 ${kpi.fillRate}%`} />
        <KpiCard label="未填充" value={String(kpi.empty)} bg={T.peach} valueColor={T.warning} caption="待人工维护（Bitable）" />
        <KpiCard label="涉及危害因素种数" value={String(kpi.factorCount)} bg={T.sky} valueColor="#005bab" caption="全岗位去重统计" />
      </div>

      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Input allowClear placeholder="岗位/职务" value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 180 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Input allowClear placeholder="部门" value={department}
            onChange={(e) => setDepartment(e.target.value)} onPressEnter={() => setApplied({ department, fillStatus })}
            style={{ width: 150 }} />
          <Select
            value={fillStatus}
            onChange={(v) => { setFillStatus(v); setApplied({ department, fillStatus: v }) }}
            options={OH_POSITION_FILL_STATUS_FILTER}
            style={{ width: 140 }} allowClear
          />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={() => setApplied({ department, fillStatus })} size="small" /></Tooltip>
        </div>

        <Table<OhPosition>
          columns={columns}
          dataSource={filtered}
          rowKey="id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 880 }}
          locale={{ emptyText: <Empty description="暂无岗位危害台账" /> }}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
          }}
        />
      </div>

      <OhPositionDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        position={detailPosition}
        hazardFactors={hazardFactors}
      />
    </div>
  )
}
