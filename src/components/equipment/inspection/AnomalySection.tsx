'use client'

import { useState, useEffect } from 'react'
import { DatePicker, Typography, Spin, App } from 'antd'
import { AlertOutlined } from '@ant-design/icons'
import { DualAxes } from '@ant-design/charts'
import dayjs from 'dayjs'
import { fetchAnomaly } from '@/lib/api/inspection-analytics'
import type { AnomalyRankingItem } from '@/types/equipment/inspection-analytics'

const { Text } = Typography
const { RangePicker } = DatePicker

// ── DESIGN.md tokens ──
const T = {
  primary: '#5645d4', canvas: '#ffffff', ink: '#1a1a1a', charcoal: '#37352f',
  slate: '#5d5b54', stone: '#a4a097', muted: '#bbb8b1',
  error: '#e03131', orange: '#dd5b00', green: '#1aae39',
  hairline: '#e5e3df',
}

const CHART_H = 300

// 组合图：柱状-异常率(左轴) + 折线-巡检总数(右轴)，降序 TOP10
function ComboRanking({ data, nameKey }: { data: any[]; nameKey: string }) {
  const sorted = [...data]
    .sort((a, b) => b.anomaly_rate - a.anomaly_rate)
    .slice(0, 10)
    .map((r) => ({
      _displayName: (r[nameKey] || ''),
      异常率: Number(r.anomaly_rate),
      巡检总数: Number(r.total_count),
    }))

  return (
    <DualAxes
      xField="_displayName"
      data={sorted}
      legend={{
        color: {
          itemMarker: (v: string) => (v === '巡检总数' ? 'smooth' : 'rect'),
        },
      }}
      children={[
        {
          type: 'interval',
          yField: '异常率',
          style: { maxWidth: 24 },
          axis: { y: { labelFormatter: (v: number) => `${v}%` } },
          tooltip: { items: [{ channel: 'y', valueFormatter: (v: number) => `${v}%` }] },
        },
        {
          type: 'line',
          yField: '巡检总数',
          style: { lineWidth: 2 },
          axis: { y: { position: 'right' } },
          tooltip: { items: [{ channel: 'y', valueFormatter: (v: number) => `${v} 次` }] },
        },
      ]}
      height={CHART_H + 40}
    />
  )
}

export function AnomalySection() {
  const { message } = App.useApp()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const [eqRanking, setEqRanking] = useState<AnomalyRankingItem[]>([])
  const [itemRanking, setItemRanking] = useState<AnomalyRankingItem[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const e = new Date(); const s = new Date(); s.setDate(s.getDate() - 30)
    setDateRange([s.toISOString().slice(0, 10), e.toISOString().slice(0, 10)])
  }, [])

  useEffect(() => {
    if (!dateRange) return
    setLoading(true)
    fetchAnomaly({ from_date: dateRange[0], to_date: dateRange[1] })
      .then(r => { setEqRanking(r.equipment_ranking); setItemRanking(r.item_ranking) })
      .catch(() => message.error('异常数据加载失败'))
      .finally(() => setLoading(false))
  }, [dateRange, message])

  const eqNamed = eqRanking.map(r => ({ ...r, _name: r.equipment_name || r.equipment_no || r.equipment_id?.slice(0, 8) || '' }))
  const itemNamed = itemRanking.map(r => ({ ...r, _name: r.item_name || r.template_item_id?.slice(0, 8) || '' }))

  const hasData = eqRanking.length > 0 || itemRanking.length > 0
  const subTitle = { fontSize: 13, fontWeight: 600, color: T.charcoal, display: 'block' as const, marginBottom: 12 }

  return (
    <div style={{ background: T.canvas, borderRadius: 12, border: `1px solid ${T.hairline}`, padding: 24 }}>
      {/* ── 标题 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <AlertOutlined style={{ color: T.error, fontSize: 18 }} />
          <span style={{ fontSize: 22, fontWeight: 600, color: T.ink }}>异常热力分析</span>
        </div>
        <RangePicker
          value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
          onChange={(_, ds) => { if (ds[0] && ds[1]) setDateRange([ds[0], ds[1]]) }}
        />
      </div>

      <Spin spinning={loading}>
        {!hasData
          ? <div style={{ padding: '80px 0', textAlign: 'center' }}>
              <Text type="secondary" style={{ fontSize: 13, color: T.stone }}>暂无异常数据</Text>
            </div>
          : (
            <>
              {/* 设备异常率排行 — 全宽 */}
              <div style={{ marginBottom: 32 }}>
                <Text style={subTitle}>设备异常率 TOP10</Text>
                {eqNamed.length > 0
                  ? <ComboRanking data={eqNamed} nameKey="_name" />
                  : <Text type="secondary" style={{ fontSize: 12, color: T.stone }}>暂无数据</Text>}
              </div>

              {/* 检查项异常率排行 — 全宽 */}
              {itemNamed.length > 0 && (
                <div>
                  <Text style={subTitle}>检查项异常率 TOP10</Text>
                  <ComboRanking data={itemNamed} nameKey="_name" />
                </div>
              )}
            </>
          )}
      </Spin>
    </div>
  )
}
