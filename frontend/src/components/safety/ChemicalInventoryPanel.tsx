'use client'

// 危化品库存管理 Panel（ChemicalInventoryPanel）— 对标 CertWarningPanel
// 顶部 KPI（stats）+ 筛选（部门/物料名称）+ 表格 + 分页 + 手动全量扫描

import { useState } from 'react'
import { App, Button, Input, Select, Table, Tag, Tooltip } from 'antd'
import { ReloadOutlined, SearchOutlined, ScanOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchChemicalInventoryRecords, fetchChemicalInventoryStats } from '@/lib/api/safety/chemical-inventory'
import { runChemicalInventoryScan } from '@/actions/safety'
import type { ChemicalInventoryRecord } from '@/types/safety'
import {
  CHEMICAL_DEPARTMENT_FILTER,
  CHEMICAL_DEPARTMENT_LABELS,
  CHEMICAL_KPI_ITEMS,
  CHEMICAL_UNIT_LABELS,
  HAZARD_CLASS_LABELS,
  RISK_FLAG_UI,
  RISK_NOTE_UI,
  CARD_STYLE,
  UI,
} from './chemicalInventoryConstants'
import { monoFont, tableCard } from './shared-styles'

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

function Pill({ value, map }: { value?: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  if (!value) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[value]
  if (!ui) return <span>{value}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

export default function ChemicalInventoryPanel() {
  const { message } = App.useApp()

  const [department, setDepartment] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')

  // 已应用筛选（点击查询后生效）
  const [applied, setApplied] = useState<{ department?: string; keyword: string }>({ keyword: '' })

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [scanning, setScanning] = useState(false)

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

  const handleScan = async () => {
    setScanning(true)
    try {
      const res = await runChemicalInventoryScan()
      if (res.code === 200 && res.data) {
        const d = res.data as { changed?: number; warn_count?: number; normal_count?: number }
        message.success(`扫描完成：${d.changed ?? 0} 条有变化 · 预警 ${d.warn_count ?? 0} · 正常 ${d.normal_count ?? 0}`)
        refresh()
      } else {
        message.error(res.message || '扫描失败')
      }
    } finally {
      setScanning(false)
    }
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
    { title: '风险标记', dataIndex: 'risk_flag', key: 'risk_flag', width: 100, render: (v: string) => <Pill value={v} map={RISK_FLAG_UI} /> },
    {
      title: '风险说明', dataIndex: 'risk_note', key: 'risk_note', width: 220,
      render: (v?: string[] | null) => {
        if (!v || v.length === 0) return <Pill value="normal" map={RISK_NOTE_UI} />
        return (
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>
            {v.map((n) => <Pill key={n} value={n} map={RISK_NOTE_UI} />)}
          </span>
        )
      },
    },
    { title: '最后更新时间', dataIndex: 'last_updated_at', key: 'last_updated_at', width: 160, render: (v?: string | null) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* KPI 卡片 */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {CHEMICAL_KPI_ITEMS.map((item) => (
          <KpiCard
            key={item.field}
            label={item.label}
            value={kpi[item.field] ?? 0}
            caption={item.caption}
            bg={item.bg}
            valueColor={item.valueColor}
          />
        ))}
      </div>

      {/* 筛选 + 操作 */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
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
        <Tooltip title="对当前台账全量重跑规则，回填风险标记/风险说明">
          <Button icon={<ScanOutlined />} loading={scanning} onClick={handleScan}>手动扫描</Button>
        </Tooltip>
        <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
      </div>

      {/* 表格 */}
      <div style={tableCard}>
        <Table<ChemicalInventoryRecord>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={isLoading}
          scroll={{ x: 1400 }}
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
      </div>
    </div>
  )
}
