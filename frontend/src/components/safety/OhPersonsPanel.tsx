'use client'

// 人员台账 Panel（OhPersonsPanel）— 对标 MsdsPanel
// KPI（4 卡）→ 筛选（部门/岗位/接触危害/最后结论/keyword）→ Table（体检记录 link → onViewExams）
// 注：后端 /oh/persons 仅支持 hazard_exposure=yes 布尔接害筛选（未支持按具体因素过滤），
//     接触危害 Select 选中任意因素即按「接害人员」筛选。

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
import dayjs from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchOhPersons, fetchOhPersonStats } from '@/lib/api/safety/occupational-health'
import type { OhPerson } from '@/types/safety'
import {
  CARD_STYLE,
  HAZARD_FACTOR_SELECT_OPTIONS,
  OH_AI_CONCLUSION_FILTER,
  OH_AI_CONCLUSION_UI,
  T,
  UI,
} from './ohConstants'
import { linkMuted, linkPrimary } from './shared-styles'
import OhPersonDrawer from './OhPersonDrawer'

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

function fmtYears(v?: number): string {
  if (v === undefined || v === null) return '-'
  const y = Math.floor(v)
  const m = Math.round((v - y) * 12)
  if (y === 0 && m === 0) return '0 年'
  if (y === 0) return `${m} 个月`
  if (m === 0) return `${y} 年`
  return `${y} 年 ${m} 个月`
}

interface OhPersonsPanelProps {
  onViewExams: (personName: string) => void
}

export default function OhPersonsPanel({ onViewExams }: OhPersonsPanelProps) {
  const [keyword, setKeyword] = useState('')
  const [department, setDepartment] = useState('')
  const [position, setPosition] = useState('')
  const [hazardFactor, setHazardFactor] = useState<string | undefined>()
  const [lastConclusion, setLastConclusion] = useState<string | undefined>()

  // 已应用筛选（点击查询时生效）
  const [applied, setApplied] = useState<{ keyword: string; department: string; position: string; hazardFactor?: string; lastConclusion?: string }>({ keyword: '', department: '', position: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [detailPerson, setDetailPerson] = useState<OhPerson | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  const queryClient = useQueryClient()

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['oh-persons-stats'],
    queryFn: fetchOhPersonStats,
  })
  const stats = statsQuery.data ?? null

  // 近30天体检人数（派生查询，一次性拉 200 条）
  const recent30dQuery = useQuery({
    queryKey: ['oh-persons-recent30d'],
    queryFn: () => fetchOhPersons({ page: 1, page_size: 200 }),
  })
  const recent30d = useMemo(() => {
    const items = recent30dQuery.data?.items ?? []
    const cutoff = dayjs().subtract(30, 'day')
    return items.filter((r) => r.last_exam_at && dayjs(r.last_exam_at).isAfter(cutoff)).length
  }, [recent30dQuery.data])

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['oh-persons', { page, pageSize, department: applied.department, position: applied.position, hazardFactor: applied.hazardFactor, lastConclusion: applied.lastConclusion, keyword: applied.keyword }],
    queryFn: () => fetchOhPersons({
      page, page_size: pageSize,
      department: applied.department.trim() || undefined,
      position: applied.position.trim() || undefined,
      hazard_exposure: applied.hazardFactor ? 'yes' : undefined,
      last_exam_conclusion: applied.lastConclusion || undefined,
      keyword: applied.keyword.trim() || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const abnormalLastExam = useMemo(() => {
    if (!stats?.by_last_exam_conclusion) return null
    return Object.entries(stats.by_last_exam_conclusion)
      .filter(([k]) => k !== 'normal')
      .reduce((sum, [, v]) => sum + (v ?? 0), 0)
  }, [stats])

  const handleSearch = () => {
    setApplied({ keyword, department, position, hazardFactor, lastConclusion })
    setPage(1)
  }

  const openDetail = (person: OhPerson) => {
    setDetailPerson(person)
    setDetailOpen(true)
  }

  const renderHazardTags = (factors: string[] | undefined) => {
    if (!factors || factors.length === 0) return <span style={{ color: UI.muted }}>-</span>
    const shown = factors.slice(0, 2)
    const rest = factors.slice(2)
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
  }

  const columns: ColumnsType<OhPerson> = useMemo(() => [
    {
      title: '姓名', dataIndex: 'name', key: 'name', width: 110, ellipsis: true,
      render: (text: string, record: OhPerson) => (
        <a onClick={() => openDetail(record)} style={{ cursor: 'pointer', fontWeight: 500, color: UI.ink }}>{text}</a>
      ),
    },
    { title: '工号', dataIndex: 'employee_no', key: 'employee_no', width: 100, render: (v: string) => v || '-' },
    { title: '部门', dataIndex: 'department', key: 'department', width: 130, ellipsis: true, render: (v: string) => v || '-' },
    { title: '岗位', dataIndex: 'position', key: 'position', width: 110, ellipsis: true, render: (v: string) => v || '-' },
    {
      title: '接害工龄', dataIndex: 'hazard_exposure_years', key: 'hazard_exposure_years', width: 110,
      render: (v: number) => fmtYears(v),
    },
    {
      title: '接触危害', dataIndex: 'hazard_factors', key: 'hazard_factors', width: 180,
      render: (v: string[] | undefined) => renderHazardTags(v),
    },
    {
      title: '体检记录', key: 'exam_count', width: 90,
      render: (_: unknown, record: OhPerson) => {
        const count = record.exam_record_ids?.length ?? 0
        if (count === 0) return <span style={{ ...linkMuted, cursor: 'default' }}>无</span>
        return (
          <span
            role="button"
            style={{ ...linkPrimary, cursor: 'pointer' }}
            onClick={() => onViewExams(record.name)}
          >
            {count} 条
          </span>
        )
      },
    },
    {
      title: '最后体检时间', dataIndex: 'last_exam_at', key: 'last_exam_at', width: 120,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '最后结论', dataIndex: 'last_exam_conclusion', key: 'last_exam_conclusion', width: 100,
      render: (v: string) => <Pill status={v} map={OH_AI_CONCLUSION_UI} />,
    },
  ], []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ padding: '0 0 32px' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <KpiCard label="总人数" value={String(stats?.total ?? '-')} bg={T.lavender} valueColor={T.primary} caption="人员汇总台账" />
        <KpiCard label="接害人数" value={String(stats?.hazard_exposed ?? '-')} bg={T.peach} valueColor={T.warning} caption="接触危害因素人员" />
        <KpiCard label="近30天已体检" value={recent30d === null ? '-' : String(recent30d)} bg={T.mint} valueColor={T.success} caption="最近一次体检在 30 天内" />
        <KpiCard label="最后体检异常" value={abnormalLastExam === null ? '-' : String(abnormalLastExam)} bg={T.rose} valueColor={T.error} caption="最后结论非未见异常" />
      </div>

      <div style={{ ...CARD_STYLE, padding: '16px 20px 20px' }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Input allowClear placeholder="姓名/工号/身份证" value={keyword}
            onChange={(e) => setKeyword(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 170 }} prefix={<SearchOutlined style={{ color: UI.muted }} />} />
          <Input allowClear placeholder="部门" value={department}
            onChange={(e) => setDepartment(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 140 }} />
          <Input allowClear placeholder="岗位" value={position}
            onChange={(e) => setPosition(e.target.value)} onPressEnter={handleSearch}
            style={{ width: 130 }} />
          <Select
            value={hazardFactor}
            onChange={(v) => { setHazardFactor(v); setApplied({ keyword, department, position, hazardFactor: v, lastConclusion }); setPage(1) }}
            options={HAZARD_FACTOR_SELECT_OPTIONS}
            placeholder="接触危害因素"
            showSearch
            allowClear
            style={{ width: 170 }}
          />
          <Select
            value={lastConclusion}
            onChange={(v) => { setLastConclusion(v); setApplied({ keyword, department, position, hazardFactor, lastConclusion: v }); setPage(1) }}
            options={OH_AI_CONCLUSION_FILTER}
            style={{ width: 140 }}
            allowClear
          />
          <Tooltip title="刷新"><Button icon={<ReloadOutlined />} onClick={handleSearch} size="small" /></Tooltip>
        </div>

        <Table<OhPerson>
          columns={columns}
          dataSource={rows}
          rowKey="id"
          loading={isLoading}
          size="middle"
          scroll={{ x: 1180 }}
          locale={{ emptyText: <Empty description="暂无人员台账" /> }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </div>

      <OhPersonDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        person={detailPerson}
        onViewExams={onViewExams}
        onSynced={() => {
          queryClient.invalidateQueries({ queryKey: ['oh-persons'] })
          queryClient.invalidateQueries({ queryKey: ['oh-persons-stats'] })
          queryClient.invalidateQueries({ queryKey: ['oh-persons-recent30d'] })
        }}
      />
    </div>
  )
}
