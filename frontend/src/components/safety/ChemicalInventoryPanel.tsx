'use client'

// 危化品库存管理 Panel（ChemicalInventoryPanel）— 对标 CertWarningPanel 形态
// StatCard 统计行（stats 端点）+ SectionCard 台账（筛选 + 表格 + 分页）
// 风险标记/说明由每日快照任务与 WS 同步链路自动回填（手动扫描入口已按 3.0 只读口径退役）。
// 2026-10-15 sheet 源口径：库存改读飞书《危险品日报表》，本就无补录入口
// （纯只读），后端补录端点在直读模式下拒绝并指向源表。

import { useState } from 'react'
import { Button, Input, Select, Table, Tag, Tooltip } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchChemicalInventoryRecords, fetchChemicalInventoryStats } from '@/lib/api/safety/chemical-inventory'
import type { ChemicalInventoryRecord } from '@/types/safety'
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import {
  CHEMICAL_DEPARTMENT_FILTER,
  CHEMICAL_DEPARTMENT_LABELS,
  CHEMICAL_KPI_ITEMS,
  CHEMICAL_UNIT_LABELS,
  HAZARD_CLASS_LABELS,
  RISK_FLAG_UI,
  RISK_NOTE_UI,
  UI,
} from './chemicalInventoryConstants'
import { monoFont } from './shared-styles'

/** KPI 字段 → ui-kit 语义 tone */
const KPI_TONE: Record<string, Tone> = {
  total_records: 'default',
  warn_count: 'warn',
  over_limit: 'danger',
  normal_count: 'ok',
}

/** 风险标记 → ui-kit 语义 tone */
const RISK_FLAG_TONE: Record<string, Tone> = {
  normal: 'ok',
  warn: 'warn',
}

/** 风险说明 → ui-kit 语义 tone */
const RISK_NOTE_TONE: Record<string, Tone> = {
  normal: 'ok',
  over_limit: 'danger',
  near_limit: 'warn',
  high_ratio: 'warn',
  incompatible_storage: 'danger',
  unclassified: 'warn',
  unit_anomaly: 'warn',
  special_storage: 'warn',
}

function Pill({ value, map, toneMap }: {
  value?: string
  map: Record<string, { label: string; color: string; bg: string }>
  toneMap: Record<string, Tone>
}) {
  if (!value) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[value]
  if (!ui) return <span>{value}</span>
  return <StatusTag tone={toneMap[value] ?? 'default'} label={ui.label} />
}

export default function ChemicalInventoryPanel() {
  const [department, setDepartment] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')

  // 已应用筛选（点击查询后生效）
  const [applied, setApplied] = useState<{ department?: string; keyword: string }>({ keyword: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const queryClient = useQueryClient()

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['chemical-inventory'] })
    queryClient.invalidateQueries({ queryKey: ['chemical-inventory-stats'] })
  }

  // 统计 query
  const statsQuery = useQuery({
    queryKey: ['chemical-inventory-stats'],
    queryFn: fetchChemicalInventoryStats,
  })
  const kpi = (statsQuery.data as unknown as Record<string, number>) ?? {}

  // 列表 query
  const { data: listData, isLoading } = useQuery({
    queryKey: ['chemical-inventory', { page, pageSize, department: applied.department, keyword: applied.keyword }],
    queryFn: () => fetchChemicalInventoryRecords({
      page, page_size: pageSize,
      department: applied.department,
      material_name: applied.keyword.trim() || undefined,
    }),
  })

  const rows = listData?.items ?? []
  const total = listData?.total ?? 0

  const handleSearch = () => {
    setApplied({ department, keyword })
    setPage(1)
  }

  const columns: ColumnsType<ChemicalInventoryRecord> = [
    { title: '物料名称', dataIndex: 'material_name', key: 'material_name', fixed: 'left', width: 160, render: (v: string) => <span style={{ fontWeight: 600, color: UI.ink }}>{v}</span> },
    { title: '部门', dataIndex: 'department', key: 'department', width: 120, render: (v: string) => CHEMICAL_DEPARTMENT_LABELS[v] ?? v },
    { title: '存放部位', dataIndex: 'storage_location', key: 'storage_location', width: 140, render: (v?: string) => v || <span style={{ color: UI.muted }}>-</span> },
    {
      title: '危险性', dataIndex: 'hazard_classes', key: 'hazard_classes', width: 180,
      render: (v?: string[] | null) => {
        if (!v || v.length === 0) return <Tag color="default">未分类</Tag>
        return (
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>
            {v.map((h) => <Tag key={h} color="blue">{HAZARD_CLASS_LABELS[h] ?? h}</Tag>)}
          </span>
        )
      },
    },
    { title: '库存数量', dataIndex: 'quantity', key: 'quantity', width: 110, align: 'right', render: (v?: number | null, r?: ChemicalInventoryRecord) => v == null ? '-' : `${v} ${CHEMICAL_UNIT_LABELS[r?.unit ?? ''] ?? r?.unit ?? ''}` },
    { title: '现场物料总量(T)', dataIndex: 'total_quantity_t', key: 'total_quantity_t', width: 140, align: 'right', render: (v?: number | null) => v == null ? '-' : <span style={monoFont}>{v}</span> },
    { title: '库存上限', dataIndex: 'max_limit', key: 'max_limit', width: 110, align: 'right', render: (v?: number | null, r?: ChemicalInventoryRecord) => v == null ? '-' : `${v} ${CHEMICAL_UNIT_LABELS[r?.max_limit_unit ?? ''] ?? r?.max_limit_unit ?? ''}` },
    { title: '风险标记', dataIndex: 'risk_flag', key: 'risk_flag', width: 100, render: (v: string) => <Pill value={v} map={RISK_FLAG_UI} toneMap={RISK_FLAG_TONE} /> },
    {
      title: '风险说明', dataIndex: 'risk_note', key: 'risk_note', width: 220,
      render: (v?: string[] | null) => {
        if (!v || v.length === 0) return <Pill value="normal" map={RISK_NOTE_UI} toneMap={RISK_NOTE_TONE} />
        return (
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>
            {v.map((n) => <Pill key={n} value={n} map={RISK_NOTE_UI} toneMap={RISK_NOTE_TONE} />)}
          </span>
        )
      },
    },
    { title: '最后更新时间', dataIndex: 'last_updated_at', key: 'last_updated_at', width: 160, render: (v?: string | null) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-' },
  ]

  return (
    <div className="flex flex-col gap-4 pb-8">
      {/* ── 统计行（stats 端点） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {CHEMICAL_KPI_ITEMS.map((item) => (
          <StatCard
            key={item.field}
            label={item.label}
            value={kpi[item.field] ?? 0}
            sub={item.caption}
            tone={KPI_TONE[item.field] ?? 'default'}
          />
        ))}
      </div>

      <SectionCard
        title="危化品库存台账"
        description={`各部门危化品库存与风险标记（共 ${total} 条）`}
      >
        {/* 筛选 + 操作 */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
          <Select
            allowClear
            placeholder="全部部门"
            style={{ width: 180 }}
            options={CHEMICAL_DEPARTMENT_FILTER}
            value={department}
            onChange={(v) => setDepartment(v || undefined)}
          />
          <Input
            allowClear
            placeholder="物料名称（模糊）"
            prefix={<SearchOutlined />}
            style={{ width: 240 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
          <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
        </div>

        <Table<ChemicalInventoryRecord>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={isLoading}
          scroll={{ x: 1400 }}
          locale={{ emptyText: <EmptyGuide compact title="暂无危化品台账记录" description="调整筛选条件后点击查询按钮应用" /> }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
            },
          }}
        />
      </SectionCard>
    </div>
  )
}
