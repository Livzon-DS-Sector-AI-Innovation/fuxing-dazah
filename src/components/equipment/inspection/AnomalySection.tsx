'use client'

import { useState, useEffect, useMemo } from 'react'
import { DatePicker, Typography, Spin, App } from 'antd'
import { AlertOutlined } from '@ant-design/icons'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { fetchAnomaly } from '@/lib/api/inspection-analytics'
import type { AnomalyMatrixCell } from '@/types/equipment/inspection-analytics'

const { Text } = Typography
const { RangePicker } = DatePicker

// ── DESIGN.md tokens ──
const T = {
  primary: '#5645d4', canvas: '#ffffff', ink: '#1a1a1a', charcoal: '#37352f',
  slate: '#5d5b54', stone: '#a4a097', muted: '#bbb8b1',
  error: '#e03131', orange: '#dd5b00', yellow: '#f5d75e', green: '#1aae39',
  hairline: '#e5e3df',
}

// 三色带：0-30 绿(正常) / 30-70 黄(预警) / 70-100 红(高危)。热力图阈值 0.7=70% 与此对齐。
const BAND = [T.green, T.yellow, T.error]

// 单设备各 cell 按次数加权聚合 → 综合异常率(用于 y 轴排序,高危设备靠前)
function aggregateRate(cells: AnomalyMatrixCell[]): number {
  const total = cells.reduce((s, c) => s + c.total_count, 0)
  const abnormal = cells.reduce((s, c) => s + c.abnormal_count, 0)
  return total ? Math.round((abnormal / total) * 1000) / 10 : 0
}

export function AnomalySection() {
  const { message } = App.useApp()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const [matrix, setMatrix] = useState<AnomalyMatrixCell[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const e = new Date(); const s = new Date(); s.setDate(s.getDate() - 30)
    setDateRange([s.toISOString().slice(0, 10), e.toISOString().slice(0, 10)])
  }, [])

  useEffect(() => {
    if (!dateRange) return
    setLoading(true)
    fetchAnomaly({ from_date: dateRange[0], to_date: dateRange[1] })
      .then(r => setMatrix(r.matrix))
      .catch(() => message.error('异常数据加载失败'))
      .finally(() => setLoading(false))
  }, [dateRange, message])

  // 每设备聚合率 + 标签(编号唯一,换行拼名称,避免 heatmap y 轴重名折叠)
  const devices = useMemo(() => {
    const byId = new Map<string, AnomalyMatrixCell[]>()
    for (const c of matrix) {
      const arr = byId.get(c.equipment_id) ?? []
      arr.push(c)
      byId.set(c.equipment_id, arr)
    }
    return [...byId.entries()]
      .map(([id, cells]) => ({
        id,
        label: cells[0].equipment_name || cells[0].equipment_no || id.slice(0, 8),
        rate: aggregateRate(cells),
      }))
      .sort((a, b) => b.rate - a.rate)
  }, [matrix])

  const labelById = useMemo(() => new Map(devices.map(d => [d.id, d.label])), [devices])

  const hasData = matrix.length > 0
  const subTitle = { fontSize: 13, fontWeight: 600, color: T.charcoal, display: 'block' as const, marginBottom: 12 }

  // 全局排查热力图 — x=检查项, y=设备, 颜色=异常率(0-100)
  // devices 已按异常率降序;yAxis inverse 让高危设备置顶
  const heatOption = useMemo<EChartsOption>(() => {
    const xCats = [...new Set(matrix.map(c => c.item_name))]
    const yCats = devices.map(d => d.label)
    return {
      grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
      tooltip: {
        // value = [巡检指标, 设备标签, 异常率]
        formatter: (p: any) => `${p.value[1]} · ${p.value[0]}<br/>异常率: ${p.value[2]}%`,
      },
      xAxis: {
        type: 'category', data: xCats, name: '巡检指标', nameGap: 28,
        splitArea: { show: true },
        axisLabel: { color: T.slate, fontSize: 11, rotate: 30, interval: 0 },
        axisLine: { lineStyle: { color: T.hairline } },
      },
      yAxis: {
        type: 'category', data: yCats, inverse: true,
        splitArea: { show: true },
        axisLabel: { color: T.slate, fontSize: 11 },
        axisLine: { lineStyle: { color: T.hairline } },
      },
      // 三色带:0 绿(正常) → 50 黄(预警) → 100 红(高危),与 70% 高危阈值观感对齐
      visualMap: { min: 0, max: 100, show: false, inRange: { color: BAND } },
      series: [{
        type: 'heatmap',
        data: matrix.map(c => [
          c.item_name,
          labelById.get(c.equipment_id) ?? c.equipment_id.slice(0, 8),
          c.anomaly_rate,
        ]),
        label: {
          show: true,
          color: '#fff', fontSize: 11,
          formatter: (p: any) => (p.value[2] > 0 ? `${p.value[2]}%` : ''),
        },
        itemStyle: { borderColor: T.canvas, borderWidth: 1 },
      }],
    }
  }, [matrix, devices, labelById])

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
            <div>
              <Text style={subTitle}>全局排查热力图（设备 × 巡检指标 异常率）</Text>
              <ReactECharts option={heatOption} style={{ height: Math.max(240, devices.length * 44) }} notMerge />
            </div>
          )}
      </Spin>
    </div>
  )
}
