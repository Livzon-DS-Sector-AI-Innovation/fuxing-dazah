'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Select, DatePicker, Typography, Spin, App } from 'antd'
import { LineChartOutlined } from '@ant-design/icons'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { fetchEquipmentList, fetchTrend } from '@/lib/api/inspection-analytics'
import type { EquipmentListItem, TrendSeries } from '@/types/equipment/inspection-analytics'

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
  surfaceSoft: '#fafaf9',  // {colors.surface-soft}
  lavenderBg: '#e6e0f5',   // {colors.card-tint-lavender}
}
const PALETTE = ['#5645d4', '#0075de', '#1aae39', '#dd5b00', '#7b3ff2', '#2a9d99', '#f5d75e', '#ff64c8']
// card-base: canvas bg, rounded-lg(12px), hairline border, padding xl(24px)
// heading-4: 22px / 600 ; button-primary: purple, rounded-md(8px), NOT pill

export function TrendSection() {
  const { message } = App.useApp()
  const [equipments, setEquipments] = useState<EquipmentListItem[]>([])
  const [selectedEq, setSelectedEq] = useState<string | null>(null)
  const [series, setSeries] = useState<TrendSeries[]>([])
  const [selectedItems, setSelectedItems] = useState<string[]>([])
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchEquipmentList()
      .then(r => { setEquipments(r.equipments); if (r.equipments.length > 0) setSelectedEq(r.equipments[0].equipment_id) })
      .catch(() => message.error('设备列表加载失败'))
  }, [message])

  const loadTrend = useCallback(async () => {
    if (!selectedEq || !dateRange) return
    setLoading(true)
    try {
      // item_ids 传空 → 后端返回该设备全部数值型参数;勾选在客户端过滤
      const r = await fetchTrend({
        equipment_id: selectedEq,
        item_ids: [],
        from_date: dateRange[0], to_date: dateRange[1],
      })
      setSeries(r.series)
      setSelectedItems(r.series.length > 0 ? [r.series[0].template_item_id] : [])  // 默认只选第一个
    } catch { setSeries([]); setSelectedItems([]) }
    finally { setLoading(false) }
  }, [selectedEq, dateRange])

  useEffect(() => { loadTrend() }, [loadTrend])

  useEffect(() => {
    const e = new Date(); const s = new Date(); s.setDate(s.getDate() - 30)
    setDateRange([s.toISOString().slice(0, 10), e.toISOString().slice(0, 10)])
  }, [])

  const { trendOption, hasData } = useMemo(() => {
    // item_ids 传空 → 后端返回全部数值型参数;此处按勾选在客户端过滤
    const vis = selectedItems.length > 0
      ? series.filter(s => selectedItems.includes(s.template_item_id))
      : series
    const pts = vis.flatMap(s =>
      s.data_points.map(dp => ({
        date: dp.date,
        value: dp.value == null ? null : Number(dp.value),  // 后端 Decimal 序列化为字符串,转数字
        name: s.unit ? `${s.item_name} (${s.unit})` : s.item_name,
      }))
    )
    const names = [...new Set(pts.map(p => p.name))]
    const dates = [...new Set(pts.map(p => p.date))].sort()
    const option: EChartsOption = {
      color: PALETTE,
      grid: { left: 52, right: 24, top: 48, bottom: 32 },
      legend: { top: 8, textStyle: { color: T.slate, fontSize: 12 } },
      tooltip: {
        trigger: 'axis',
        valueFormatter: v => (v == null ? '-' : Number(v as number).toFixed(2)),
      },
      xAxis: {
        type: 'category', data: dates, name: '日期',
        boundaryGap: false,
        axisLabel: { color: T.stone, fontSize: 11 },
        axisLine: { lineStyle: { color: T.hairline } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: T.stone, fontSize: 11 },
        splitLine: { lineStyle: { color: T.hairline } },
      },
      series: names.map(name => ({
        name, type: 'line', symbolSize: 5, connectNulls: true,
        data: dates.map(d => {
          const pt = pts.find(p => p.name === name && p.date === d)
          return pt ? pt.value : null
        }),
      })),
    }
    return { trendOption: option, hasData: pts.length > 0 }
  }, [series, selectedItems])

  return (
    <div style={{ background: T.canvas, borderRadius: 12, border: `1px solid ${T.hairline}`, padding: 24, marginBottom: 48 }}>
      {/* ── 标题 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
        <LineChartOutlined style={{ color: T.primary, fontSize: 18 }} />
        <span style={{ fontSize: 22, fontWeight: 600, color: T.ink }}>设备参数趋势</span>
      </div>

      {/* ── 选择器 ── */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <Select
          value={selectedEq} onChange={(v: string) => { setSelectedEq(v); setSelectedItems([]) }}
          showSearch optionFilterProp="label" placeholder="选择设备"
          style={{ minWidth: 220 }}
          options={equipments.map(e => ({ label: `${e.equipment_name}（${e.equipment_no}）`, value: e.equipment_id }))}
        />
        <RangePicker
          value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
          onChange={(_, ds) => { if (ds[0] && ds[1]) setDateRange([ds[0], ds[1]]) }}
        />
      </div>

      {/* ── 检查项切换 (pill-tab 激活态) ── */}
      {series.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
          {series.map(s => {
            const active = selectedItems.includes(s.template_item_id)
            return (
              <button key={s.template_item_id}
                onClick={() => setSelectedItems(prev =>
                  prev.includes(s.template_item_id) ? prev.filter(id => id !== s.template_item_id) : [...prev, s.template_item_id]
                )}
                style={{
                  padding: '6px 14px', borderRadius: 20,
                  border: active ? `1px solid ${T.primary}` : `1px solid ${T.hairline}`,
                  background: active ? T.lavenderBg : T.surfaceSoft,
                  color: active ? T.primary : T.slate, fontSize: 13, fontWeight: active ? 600 : 400,
                  cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.15s',
                }}>
                {s.item_name}{s.unit ? ` (${s.unit})` : ''}
              </button>
            )
          })}
        </div>
      )}

      {/* ── 折线图 ── */}
      <Spin spinning={loading}>
        {hasData
          ? <ReactECharts option={trendOption} style={{ height: 320 }} notMerge />
          : <div style={{ padding: '60px 0', textAlign: 'center' }}>
              <Text type="secondary" style={{ fontSize: 13, color: T.stone }}>选择设备和时间范围后查看参数趋势</Text>
            </div>}
      </Spin>
    </div>
  )
}
