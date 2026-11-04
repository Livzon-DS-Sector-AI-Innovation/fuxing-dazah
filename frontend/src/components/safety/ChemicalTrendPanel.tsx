'use client'

// 危化品趋势看板 Panel — daily 快照只读聚合（后端 chemical_inventory/trend.py）
// KPI 统计行（最新快照口径）+ 三张占比仪表（GaugeChart）+ 两张趋势图（总量/异动）
// + 异动明细表（目标快照日 vs 前一快照日，部门×物料粒度，急剧变化阈值与日报同源）。

import { useState } from 'react'
import { Select, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import {
  fetchChemicalInventoryChanges,
  fetchChemicalInventoryChangeTrend,
  fetchChemicalInventoryStats,
  fetchChemicalInventoryTrend,
} from '@/lib/api/safety/chemical-inventory'
import type { ChemicalChangeFlag, ChemicalChangeItem } from '@/types/safety'
import {
  EmptyGuide,
  GaugeChart,
  SectionCard,
  SingleTrendChart,
  StatCard,
  StatusTag,
  TrendAreaChart,
} from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import { CHEMICAL_DEPARTMENT_LABELS, UI } from './chemicalInventoryConstants'
import { monoFont } from './shared-styles'

/** 异动标记 → ui-kit 语义 tone */
const CHANGE_FLAG_UI: Record<ChemicalChangeFlag, { label: string; tone: Tone }> = {
  surge: { label: '急剧上升', tone: 'danger' },
  decline: { label: '急剧下降', tone: 'info' },
  new: { label: '新增', tone: 'primary' },
  removed: { label: '已清零', tone: 'default' },
  normal: { label: '波动', tone: 'default' },
}

const RANGE_OPTIONS = [
  { value: 7, label: '近 7 个快照日' },
  { value: 14, label: '近 14 个快照日' },
  { value: 30, label: '近 30 个快照日' },
  { value: 90, label: '近 90 个快照日' },
]

/** 占比仪表阈值带（纯展示口径）：ok < warn < danger */
const BANDS_10_25 = [{ to: 10, tone: 'ok' as const }, { to: 25, tone: 'warn' as const }, { to: 100, tone: 'danger' as const }]
const BANDS_10_20 = [{ to: 10, tone: 'ok' as const }, { to: 20, tone: 'warn' as const }, { to: 100, tone: 'danger' as const }]
const BANDS_0_5 = [{ to: 0, tone: 'ok' as const }, { to: 5, tone: 'warn' as const }, { to: 100, tone: 'danger' as const }]

function pct(numerator: number | undefined, denominator: number | undefined): number {
  if (!numerator || !denominator || denominator <= 0) return 0
  return Math.min(100, (numerator / denominator) * 100)
}

function fmtSigned(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (v === 0) return '持平'
  return `${v > 0 ? '+' : ''}${v}`
}

function fmtT(v: number | null | undefined): string {
  return v == null ? '-' : String(v)
}

export default function ChemicalTrendPanel() {
  const [days, setDays] = useState(30)

  const trendQuery = useQuery({
    queryKey: ['chemical-inventory-trend', days],
    queryFn: () => fetchChemicalInventoryTrend(days),
  })
  const changeTrendQuery = useQuery({
    queryKey: ['chemical-inventory-change-trend', days],
    queryFn: () => fetchChemicalInventoryChangeTrend(days),
  })
  const changesQuery = useQuery({
    queryKey: ['chemical-inventory-changes'],
    queryFn: () => fetchChemicalInventoryChanges(200),
  })
  const statsQuery = useQuery({
    queryKey: ['chemical-inventory-stats'],
    queryFn: fetchChemicalInventoryStats,
  })

  const points = trendQuery.data?.points ?? []
  const latest = points[points.length - 1]
  const prevPoint = points.length > 1 ? points[points.length - 2] : undefined
  const totalDelta =
    latest?.total_t != null && prevPoint?.total_t != null
      ? Math.round((latest.total_t - prevPoint.total_t) * 10000) / 10000
      : null

  const changes = changesQuery.data
  const changePoints = changeTrendQuery.data?.points ?? []
  const stats = (statsQuery.data as unknown as Record<string, number>) ?? {}
  const abnormalCount = (changes?.summary.surge_count ?? 0) + (changes?.summary.decline_count ?? 0)

  const columns: ColumnsType<ChemicalChangeItem> = [
    {
      title: '标记', dataIndex: 'flag', key: 'flag', width: 110,
      render: (flag: ChemicalChangeFlag) => {
        const ui = CHANGE_FLAG_UI[flag] ?? CHANGE_FLAG_UI.normal
        return <StatusTag tone={ui.tone} label={ui.label} />
      },
    },
    {
      title: '部门', dataIndex: 'department', key: 'department', width: 140,
      render: (v: string) => CHEMICAL_DEPARTMENT_LABELS[v] ?? v,
    },
    {
      title: '物料名称', dataIndex: 'material_name', key: 'material_name', width: 180, ellipsis: true,
      render: (v: string) => <span style={{ fontWeight: 600, color: UI.ink }}>{v}</span>,
    },
    { title: '昨日(T)', dataIndex: 'prev_t', key: 'prev_t', width: 100, align: 'right', render: fmtT },
    { title: '今日(T)', dataIndex: 'cur_t', key: 'cur_t', width: 100, align: 'right', render: fmtT },
    {
      title: '变化量(T)', dataIndex: 'delta_t', key: 'delta_t', width: 110, align: 'right',
      // 后端已按 |Δ| 降序给出
      render: (v: number | null) => (
        <span style={{ ...monoFont, color: v == null ? UI.muted : v > 0 ? 'var(--wh-danger)' : v < 0 ? 'var(--wh-info)' : UI.muted }}>
          {fmtSigned(v)}
        </span>
      ),
    },
    {
      title: '变化率', dataIndex: 'ratio', key: 'ratio', width: 90, align: 'right',
      render: (v: number | null) => (v == null ? <span style={{ color: UI.muted }}>—</span> : (
        <span style={{ ...monoFont, color: v > 0 ? 'var(--wh-danger)' : 'var(--wh-info)' }}>
          {fmtSigned(Math.round(v * 1000) / 10)}%
        </span>
      )),
    },
  ]

  const thresholdDesc = changes?.thresholds
    ? `判定阈值：变化 ≥${changes.thresholds.abs_t}T 且变化率 ≥${Math.round(changes.thresholds.ratio * 100)}%（与库存日报同源）`
    : undefined

  return (
    <div className="flex flex-col gap-4 pb-8">
      {/* ── 趋势窗口（仅作用两张趋势图） ── */}
      <div className="flex items-center justify-end gap-2">
        <span className="text-[12px]" style={{ color: UI.muted }}>趋势窗口</span>
        <Select options={RANGE_OPTIONS} value={days} onChange={setDays} style={{ width: 150 }} />
      </div>

      {/* ── KPI 行（最新快照日口径；超限来自实时台账统计） ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="库存总量（T）"
          value={latest?.total_t ?? '—'}
          loading={trendQuery.isLoading}
          sub={latest ? `较前一快照日 ${fmtSigned(totalDelta)} T` : '暂无快照数据'}
        />
        <StatCard
          label="预警条目"
          value={latest?.warn_count ?? '—'}
          tone="warn"
          loading={trendQuery.isLoading}
          sub={latest ? `快照日 ${latest.date}` : undefined}
        />
        <StatCard
          label="超限条目"
          value={stats.over_limit ?? '—'}
          tone="danger"
          loading={statsQuery.isLoading}
          sub="当前台账实时口径"
        />
        <StatCard
          label="异动物料"
          value={changes ? abnormalCount : '—'}
          tone="info"
          loading={changesQuery.isLoading}
          sub={changes?.target_date ? `${changes.target_date} 急剧上升/下降` : undefined}
        />
      </div>

      {/* ── 占比仪表行 ── */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <SectionCard title="预警条目占比" description="风险标记=预警 的条目占比（快照口径）">
          {latest ? (
            <GaugeChart
              value={pct(latest.warn_count, latest.item_count)}
              label={`${latest.warn_count} / ${latest.item_count} 条`}
              bands={BANDS_10_25}
            />
          ) : (
            <EmptyGuide compact title="暂无快照数据" />
          )}
        </SectionCard>
        <SectionCard title="异动物料占比" description="急剧上升/下降物料占今日在账物料比例">
          {changes && changes.target_date ? (
            <GaugeChart
              value={pct(abnormalCount, changes.summary.total_materials)}
              label={`${abnormalCount} / ${changes.summary.total_materials} 项`}
              bands={BANDS_10_20}
            />
          ) : (
            <EmptyGuide compact title="暂无快照数据" />
          )}
        </SectionCard>
        <SectionCard title="超限条目占比" description="现场总量超过库存上限的条目占比（实时台账）">
          {stats.total_records != null ? (
            <GaugeChart
              value={pct(stats.over_limit, stats.total_records)}
              label={`${stats.over_limit ?? 0} / ${stats.total_records} 条`}
              bands={BANDS_0_5}
            />
          ) : (
            <EmptyGuide compact title="暂无台账统计" />
          )}
        </SectionCard>
      </div>

      {/* ── 趋势图行 ── */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <SectionCard title="库存总量趋势" description={`近 ${days} 个快照日 · 现场物料总量合计（T）`}>
          <SingleTrendChart
            dates={points.map(p => p.date)}
            values={points.map(p => p.total_t ?? 0)}
            label="库存总量(T)"
            tone="primary"
            height={260}
            emptyText="暂无 daily 快照（每日 19:30 落库）"
          />
        </SectionCard>
        <SectionCard title="异动趋势" description={`近 ${days} 个快照日 · 急剧上升/下降条数（较前一快照日）`}>
          <TrendAreaChart
            dates={changePoints.map(p => p.date)}
            seriesA={changePoints.map(p => p.surge_count)}
            seriesB={changePoints.map(p => p.decline_count)}
            labelA="急剧上升"
            labelB="急剧下降"
            toneA="danger"
            toneB="info"
            height={260}
            emptyText="暂无 daily 快照（每日 19:30 落库）"
          />
        </SectionCard>
      </div>

      {/* ── 异动明细 ── */}
      <SectionCard
        title="异动明细"
        description={
          changes?.target_date
            ? `${changes.target_date} vs ${changes.base_date ?? '—'} · ${thresholdDesc ?? ''}`
            : '最新快照日 vs 前一快照日'
        }
      >
        {changes?.compare_skipped ? (
          <EmptyGuide
            compact
            title="环比断点"
            description="前后两日快照数据源口径不一致（切换/回滚日），变化明细不可比"
          />
        ) : (
          <Table<ChemicalChangeItem>
            rowKey={r => `${r.department}:${r.material_name}`}
            columns={columns}
            dataSource={changes?.items ?? []}
            loading={changesQuery.isLoading}
            scroll={{ x: 860 }}
            locale={{ emptyText: <EmptyGuide compact title="两快照日间无异动" description="所有部门×物料组合的库存总量均无变化" /> }}
            pagination={{ pageSize: 10, size: 'small', showTotal: t => `共 ${t} 条` }}
          />
        )}
      </SectionCard>
    </div>
  )
}
