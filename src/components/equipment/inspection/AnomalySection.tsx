'use client'

import { useState, useEffect } from 'react'
import { DatePicker, Typography, Spin, App } from 'antd'
import { AlertOutlined } from '@ant-design/icons'
import { Bar, Column } from '@ant-design/charts'
import dayjs from 'dayjs'
import { fetchAnomaly } from '@/lib/api/inspection-analytics'
import type { AnomalyRankingItem, AnomalyMonthlyItem } from '@/types/equipment/inspection-analytics'

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

// 横向柱状图：异常率降序,严重度分色(签名元素——高异常率红/橙)
function RankingBar({ data, nameKey }: { data: any[]; nameKey: string }) {
  const sorted = [...data].sort((a, b) => b.anomaly_rate - a.anomaly_rate)
  const range = sorted.map(r => (r.anomaly_rate >= 30 ? T.error : r.anomaly_rate >= 15 ? T.orange : T.primary))
  return (
    <Bar
      data={sorted}
      xField="anomaly_rate"
      yField={nameKey}
      colorField={nameKey}
      scale={{ color: { range } }}
      axis={{ y: { labelFormatter: (v: string) => (v && v.length > 14 ? v.slice(0, 14) + '…' : v) } }}
      legend={false}
      height={CHART_H}
      marginLeft={140}
      tooltip={{ channel: 'x', name: '异常率', valueFormatter: (v: number) => `${v}%` }}
    />
  )
}

export function AnomalySection() {
  const { message } = App.useApp()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const [eqRanking, setEqRanking] = useState<AnomalyRankingItem[]>([])
  const [itemRanking, setItemRanking] = useState<AnomalyRankingItem[]>([])
  const [monthly, setMonthly] = useState<AnomalyMonthlyItem[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const e = new Date(); const s = new Date(); s.setDate(s.getDate() - 30)
    setDateRange([s.toISOString().slice(0, 10), e.toISOString().slice(0, 10)])
  }, [])

  useEffect(() => {
    if (!dateRange) return
    setLoading(true)
    fetchAnomaly({ from_date: dateRange[0], to_date: dateRange[1] })
      .then(r => { setEqRanking(r.equipment_ranking); setItemRanking(r.item_ranking); setMonthly(r.monthly_trend) })
      .catch(() => message.error('异常数据加载失败'))
      .finally(() => setLoading(false))
  }, [dateRange, message])

  const eqNamed = eqRanking.map(r => ({ ...r, _name: r.equipment_name || r.equipment_no || r.equipment_id?.slice(0, 8) || '' }))
  const itemNamed = itemRanking.map(r => ({ ...r, _name: r.item_name || r.template_item_id?.slice(0, 8) || '' }))

  // 月度堆叠柱：正常/异常/跳过
  const monthData = monthly.flatMap(m => [
    { month: m.month, type: '正常', value: m.normal },
    { month: m.month, type: '异常', value: m.abnormal },
    { month: m.month, type: '跳过', value: m.skip },
  ])

  const hasData = eqRanking.length > 0 || itemRanking.length > 0 || monthly.length > 0
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
              {/* 上层: 设备排行 × 月度趋势 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 32 }}>
                <div>
                  <Text style={subTitle}>设备异常率 TOP10</Text>
                  {eqNamed.length > 0
                    ? <RankingBar data={eqNamed} nameKey="_name" />
                    : <Text type="secondary" style={{ fontSize: 12, color: T.stone }}>暂无数据</Text>}
                </div>
                <div>
                  <Text style={subTitle}>月度异常趋势</Text>
                  {monthly.length > 0
                    ? <Column
                        data={monthData}
                        xField="month"
                        yField="value"
                        colorField="type"
                        stack
                        scale={{ color: { domain: ['正常', '异常', '跳过'], range: [T.green, T.error, T.muted] } }}
                        axis={{ x: { title: '月份' }, y: { title: false } }}
                        legend={{ color: { position: 'top' } }}
                        height={CHART_H}
                      />
                    : <Text type="secondary" style={{ fontSize: 12, color: T.stone }}>暂无数据</Text>}
                </div>
              </div>

              {/* 下层: 检查项排行 */}
              {itemNamed.length > 0 && (
                <div>
                  <Text style={subTitle}>检查项异常率 TOP10</Text>
                  <RankingBar data={itemNamed} nameKey="_name" />
                </div>
              )}
            </>
          )}
      </Spin>
    </div>
  )
}
