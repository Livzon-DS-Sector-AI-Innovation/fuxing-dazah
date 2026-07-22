'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { DatePicker, Typography, Spin, App } from 'antd'
import { LineChartOutlined } from '@ant-design/icons'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { fetchLinkage } from '@/lib/api/inspection-analytics'
import type { LinkagePoint } from '@/types/equipment/inspection-analytics'

const { Text } = Typography
const { RangePicker } = DatePicker

// ── DESIGN.md tokens ──
const T = {
  primary: '#5645d4',      // {colors.primary}
  canvas: '#ffffff',       // {colors.canvas}
  ink: '#1a1a1a',          // {colors.ink}
  slate: '#5d5b54',        // {colors.slate}
  stone: '#a4a097',        // {colors.stone}
  hairline: '#e5e3df',     // {colors.hairline}
}
const PALETTE = ['#5645d4', '#0075de', '#1aae39', '#dd5b00', '#7b3ff2', '#2a9d99']

export function LinkageSection() {
  const { message } = App.useApp()
  const [points, setPoints] = useState<LinkagePoint[]>([])
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const [loading, setLoading] = useState(false)

  // 默认近 12 个月（月级趋势）
  useEffect(() => {
    const e = new Date(); const s = new Date(); s.setMonth(s.getMonth() - 11)
    setDateRange([s.toISOString().slice(0, 10), e.toISOString().slice(0, 10)])
  }, [])

  const loadLinkage = useCallback(async () => {
    if (!dateRange) return
    setLoading(true)
    try {
      const r = await fetchLinkage({ from_date: dateRange[0], to_date: dateRange[1] })
      setPoints(r.points)
    } catch { setPoints([]); message.error('联动分析加载失败') }
    finally { setLoading(false) }
  }, [dateRange, message])

  useEffect(() => { loadLinkage() }, [loadLinkage])

  const linkageOption = useMemo<EChartsOption>(() => {
    const names = [...new Set(points.map(p => p.series))]
    const months = [...new Set(points.map(p => p.month))].sort()
    return {
      color: PALETTE,
      grid: { left: 52, right: 24, top: 48, bottom: 32 },
      legend: { top: 8, textStyle: { color: T.slate, fontSize: 12 } },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category', data: months, name: '月份',
        boundaryGap: false,
        axisLabel: { color: T.stone, fontSize: 11 },
        axisLine: { lineStyle: { color: T.hairline } },
      },
      yAxis: {
        type: 'value', name: '次数',
        axisLabel: { color: T.stone, fontSize: 11 },
        splitLine: { lineStyle: { color: T.hairline } },
      },
      series: names.map(name => ({
        name, type: 'line', symbolSize: 5, connectNulls: true,
        data: months.map(m => {
          const pt = points.find(p => p.series === name && p.month === m)
          return pt ? pt.count : null
        }),
      })),
    }
  }, [points])

  return (
    <div style={{ background: T.canvas, borderRadius: 12, border: `1px solid ${T.hairline}`, padding: 24, marginTop: 48 }}>
      {/* ── 标题 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <LineChartOutlined style={{ color: T.primary, fontSize: 18 }} />
        <span style={{ fontSize: 22, fontWeight: 600, color: T.ink }}>巡检-维修联动分析</span>
      </div>
      <Text style={{ fontSize: 13, color: T.slate, display: 'block', marginBottom: 20 }}>
        按月叠加巡检异常数与各类型工单量。异常↑且故障维修↓，说明巡检提前拦截了小问题、避免了大故障。
      </Text>

      {/* ── 时间范围 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <RangePicker
          value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
          onChange={(_, ds) => { if (ds[0] && ds[1]) setDateRange([ds[0], ds[1]]) }}
        />
      </div>

      {/* ── 双曲线叠加折线图（多序列共用 Y 轴） ── */}
      <Spin spinning={loading}>
        {points.length > 0
          ? <ReactECharts option={linkageOption} style={{ height: 320 }} notMerge />
          : <div style={{ padding: '60px 0', textAlign: 'center' }}>
              <Text type="secondary" style={{ fontSize: 13, color: T.stone }}>选择时间范围后查看巡检与维修的联动趋势</Text>
            </div>}
      </Spin>
    </div>
  )
}
