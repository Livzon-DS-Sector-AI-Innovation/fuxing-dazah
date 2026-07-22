'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { DatePicker, Segmented, Spin, Empty, message, Table } from 'antd'
import { Line, Bar } from '@ant-design/charts'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchEnergyOverview } from '@/lib/api/energy'
import type { EnergyOverview, DistributionRow, EnergyTypeMeta } from '@/types/energy'

const { RangePicker } = DatePicker

const RANGE_PRESETS: Record<string, [dayjs.Dayjs, dayjs.Dayjs]> = {
  '昨天': [dayjs().subtract(1, 'day').startOf('day'), dayjs().subtract(1, 'day').endOf('day')],
  '7天': [dayjs().subtract(6, 'day').startOf('day'), dayjs().endOf('day')],
  '30天': [dayjs().subtract(29, 'day').startOf('day'), dayjs().endOf('day')],
  '本月': [dayjs().startOf('month'), dayjs().endOf('day')],
}

// ── 趋势计算（线性回归） ──
function computeTrend(values: number[]): { direction: 'up' | 'down' | 'flat'; pct: number } | null {
  const n = values.length
  if (n < 2) return null

  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0
  for (let i = 0; i < n; i++) {
    sumX += i
    sumY += values[i]
    sumXY += i * values[i]
    sumX2 += i * i
  }
  const denom = n * sumX2 - sumX * sumX
  if (denom === 0) return null

  const slope = (n * sumXY - sumX * sumY) / denom
  const avgY = sumY / n
  if (avgY === 0) return { direction: 'flat', pct: 0 }

  const totalChange = slope * (n - 1)
  const pct = Math.round((totalChange / avgY) * 1000) / 10 // 保留一位小数

  const absPct = Math.abs(pct)
  if (absPct < 10) return { direction: 'flat', pct }
  return { direction: pct > 0 ? 'up' : 'down', pct }
}

export default function VisualizationPage() {
  const [range, setRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>(RANGE_PRESETS['7天'])
  const [activePreset, setActivePreset] = useState<string>('7天')
  const [selectedType, setSelectedType] = useState<string | null>(null)
  const [selectedWorkshop, setSelectedWorkshop] = useState<string | null>(null)
  const [overview, setOverview] = useState<EnergyOverview | null>(null)
  const [prevOverview, setPrevOverview] = useState<EnergyOverview | null>(null)
  const [loading, setLoading] = useState(false)

  const days = range[1].diff(range[0], 'day') + 1

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = range[1].diff(range[0], 'day') + 1
      const [curr, prev] = await Promise.all([
        fetchEnergyOverview({
          start_time: range[0].toISOString(),
          end_time: range[1].toISOString(),
          granularity: 'daily',
          energy_type: selectedType || undefined,
        }),
        fetchEnergyOverview({
          start_time: range[0].subtract(d, 'day').toISOString(),
          end_time: range[1].subtract(d, 'day').toISOString(),
          granularity: 'daily',
          energy_type: selectedType || undefined,
        }),
      ])
      setOverview(curr)
      setPrevOverview(prev)
    } catch {
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [range, selectedType])

  useEffect(() => { load() }, [load])
  useEffect(() => { setSelectedWorkshop(null) }, [selectedType])

  const metadata = overview?.type_metadata || []

  // ── KPI（按当前选中能源类型计算，非全部能源相加）──
  const kpi = useMemo(() => {
    const summary = overview?.summary || {}
    const prevSummary = prevOverview?.summary || {}
    const trends = overview?.trend || []

    // 确定实际使用的能源类型
    const activeType = selectedType || metadata[0]?.type_code || ''
    const activeMeta = metadata.find((m) => m.type_code === activeType)
    const unit = activeMeta?.unit || ''

    const k = `total_${activeType}`
    const total = (summary[k] as number) ?? (summary[activeType] as number) ?? 0
    const prevTotal = (prevSummary[k] as number) ?? (prevSummary[activeType] as number) ?? 0

    const avg = days > 0 ? total / days : 0
    const pctChange = prevTotal > 0 ? ((total - prevTotal) / prevTotal) * 100 : 0

    // 峰值日（仅当前能源类型）
    const typeTrends = trends.filter((t) => t.type === activeType)
    let peakDay = '', peakVal = 0
    for (const t of typeTrends) {
      if (t.value > peakVal) { peakVal = t.value; peakDay = t.time }
    }

    // 最高车间（当前能源类型）
    const ws = overview?.workshop_distribution || []
    const typeWs = selectedType ? ws.filter((w) => w.energy_type === selectedType) : ws
    const wm: Record<string, number> = {}
    for (const w of typeWs) wm[w.group_key] = (wm[w.group_key] || 0) + w.total_value
    let topWs = '', topWsVal = 0
    for (const [k, v] of Object.entries(wm)) { if (v > topWsVal) { topWsVal = v; topWs = k } }

    return {
      total, avg, pctChange, peakDay: peakDay ? dayjs(peakDay).format('MM-DD') : '—',
      topWorkshop: topWs || '—', unit, activeMeta,
    }
  }, [overview, prevOverview, metadata, days, selectedType])

  // ── 堆叠面积图 ──
  const areaData = useMemo(() => {
    const raw = overview?.trend || []
    return raw.map((t) => ({
      date: dayjs(t.time).format('MM-DD'),
      value: t.value,
      type: metadata.find((m) => m.type_code === t.type)?.display_name || t.type,
    }))
  }, [overview, metadata])

  const areaColors = useMemo(() => {
    const colors = metadata.map((m) => m.color).filter((c): c is string => !!c)
    return colors.length > 0 ? colors : ['#1677ff', '#1aae39', '#dd5b00', '#722ed1', '#2f54eb', '#fa541c', '#faad14']
  }, [metadata])

  const unitMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const t of metadata) m[t.display_name] = t.unit
    return m
  }, [metadata])

  const lineConfig = useMemo(() => ({
    data: areaData,
    xField: 'date',
    yField: 'value',
    seriesField: 'type',
    smooth: true,
    height: 340,
    point: { size: 3, shape: 'circle' },
    legend: { position: 'top' as const },
    xAxis: { label: { autoRotate: false }, grid: null },
    yAxis: { grid: { line: { style: { stroke: '#f0f0f0', lineDash: [3, 3] } } } },
    tooltip: {
      crosshairs: { type: 'xy' as const },
      items: [
        {
          channel: 'y',
          valueFormatter: (v: number, d: any) => {
            const u = unitMap[d?.type] || ''
            return `${v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} ${u}`
          },
        },
      ],
    },
    color: areaColors,
  }), [areaData, areaColors, unitMap])

  // ── 车间排名 ──
  const workshopData = useMemo(() => {
    const rows = overview?.workshop_distribution || []
    const filtered = selectedType ? rows.filter((r) => r.energy_type === selectedType) : rows
    const m: Record<string, number> = {}
    for (const r of filtered) m[r.group_key] = (m[r.group_key] || 0) + r.total_value
    return Object.entries(m)
      .map(([name, val]) => ({ workshop: name || '未知', value: val }))
      .sort((a, b) => b.value - a.value)
  }, [overview, selectedType])

  const maxWs = workshopData[0]?.value || 1

  // ── 区域横向条形图 ──
  const plBarData = useMemo(() => {
    const rows = overview?.production_line_distribution || []
    const merged: Record<string, { name: string; workshop: string; value: number }> = {}
    for (const r of rows) {
      const key = `${r.workshop || '未知'}｜${r.group_key || '未知'}`
      if (!merged[key]) merged[key] = { name: r.group_key || '未知', workshop: r.workshop || '未知', value: 0 }
      merged[key].value += r.total_value
    }
    let list = Object.values(merged).sort((a, b) => b.value - a.value)
    if (selectedWorkshop) list = list.filter((d) => d.workshop === selectedWorkshop)
    return list.slice(0, 15)
  }, [overview, selectedWorkshop])

  const workshopColors = ['#5645d4', '#1677ff', '#1aae39', '#dd5b00', '#722ed1', '#2f54eb', '#fa541c', '#faad14']

  const plBarConfig = useMemo(() => {
    // 按车间分配颜色
    const colorMap: Record<string, string> = {}
    const uniqueWorkshops = [...new Set(plBarData.map((d) => d.workshop).filter((w) => w && w !== '未知'))]
    uniqueWorkshops.forEach((w, i) => { colorMap[w] = workshopColors[i % workshopColors.length] })

    return {
      data: plBarData.map((d) => ({
        ...d,
        label: d.workshop && d.workshop !== '未知' ? `${d.name}（${d.workshop}）` : d.name,
      })),
      xField: 'value',
      yField: 'label',
      height: Math.max(220, Math.min(420, plBarData.length * 36)),
      barWidthRatio: 0.65,
      color: (d: Record<string, unknown>) => colorMap[d.workshop as string] || '#5645d4',
      label: {
        position: 'right' as const,
        text: (d: any) => `${(d.value ?? 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`,
        style: { fontSize: 11, fill: '#5d5b54' },
      },
      xAxis: {
        label: {
          formatter: (v: string) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }),
        },
        grid: { line: { style: { stroke: '#f0f0f0', lineDash: [3, 3] } } },
      },
      yAxis: {
        position: 'left' as const,
        label: { autoEllipsis: true, style: { fontSize: 12 } },
      },
    }
  }, [plBarData])

  // ── 详情表 ──
  const detailColumns = useMemo(() => [
    {
      title: '能源类型', dataIndex: 'type', key: 'type', width: 140,
      render: (_: unknown, r: any) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: r.color, display: 'inline-block' }} />
          <span style={{ fontWeight: 500 }}>{r.display_name}</span>
        </span>
      ),
    },
    { title: '总量', dataIndex: 'total', key: 'total', width: 120, align: 'right' as const,
      render: (v: number) => v.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) },
    { title: '占比', dataIndex: 'pct', key: 'pct', width: 70, align: 'right' as const,
      render: (v: number) => <span style={{ color: '#787671' }}>{v.toFixed(1)}%</span> },
    { title: '日均', dataIndex: 'dailyAvg', key: 'dailyAvg', width: 100, align: 'right' as const,
      render: (v: number) => v.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) },
    { title: '峰值', dataIndex: 'peak', key: 'peak', width: 100, align: 'right' as const,
      render: (v: number) => v.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) },
    { title: '趋势', dataIndex: 'sparkline', key: 'sparkline', width: 100,
      render: (_: unknown, r: any) => {
        const trend = computeTrend(r.sparkline)
        if (!trend) return <span style={{ color: '#c8c4be' }}>—</span>
        const sign = trend.pct >= 0 ? '+' : ''
        const icon = trend.direction === 'up' ? '↑' : trend.direction === 'down' ? '↓' : '→'
        const color = trend.direction === 'up' ? '#e03131' : trend.direction === 'down' ? '#1aae39' : '#a4a097'
        return <span style={{ color, fontWeight: 500, fontSize: 13 }}>{icon} {sign}{trend.pct}%</span>
      },
    },
  ], [days])

  const detailData = useMemo(() => {
    const summary = overview?.summary || {}
    const trends = overview?.trend || []
    // 占比用的全类型合计（仅表格展示用，不用于 KPI）
    let grandTotal = 0
    for (const m of metadata) {
      const k = `total_${m.type_code}`
      grandTotal += (summary[k] as number) ?? (summary[m.type_code] as number) ?? 0
    }
    // 生成完整日期列表，用于补齐 sparkline 缺失日期（填 0，保留时间间距）
    const dateList = Array.from({ length: days }, (_, i) =>
      range[0].add(i, 'day').format('YYYY-MM-DD'),
    )
    return metadata.map((m) => {
      const k = `total_${m.type_code}`
      const total = (summary[k] as number) ?? (summary[m.type_code] as number) ?? 0
      const typeTrends = trends
        .filter((t) => t.type === m.type_code)
        .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())
      const peak = typeTrends.reduce((max, t) => Math.max(max, t.value), 0)
      // 日期→值映射，缺失日期填 0
      const valueMap: Record<string, number> = {}
      for (const t of typeTrends) {
        valueMap[dayjs(t.time).format('YYYY-MM-DD')] = t.value
      }
      return {
        key: m.type_code,
        display_name: m.display_name,
        type: m.type_code,
        color: m.color || '#999',
        total,
        pct: grandTotal > 0 ? (total / grandTotal) * 100 : 0,
        dailyAvg: days > 0 ? total / days : 0,
        peak,
        sparkline: dateList.map((d) => valueMap[d] ?? 0),
      }
    }).filter((d) => d.total > 0)
  }, [overview, metadata, days, range])

  // ── Date handlers ──
  const handlePreset = (val: string) => {
    setActivePreset(val)
    if (RANGE_PRESETS[val]) setRange(RANGE_PRESETS[val])
  }
  const handleRangeChange = (d: [dayjs.Dayjs | null, dayjs.Dayjs | null] | null) => {
    if (d?.[0] && d?.[1]) { setRange([d[0], d[1]]); setActivePreset('') }
  }

  return (
    <div style={{ padding: '28px 32px', minHeight: '100%', background: '#fafaf9' }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 24, fontWeight: 500, margin: 0, color: '#1a1a1a' }}>能源分析</h1>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <Segmented
            options={Object.keys(RANGE_PRESETS)}
            value={activePreset}
            onChange={(v) => handlePreset(v as string)}
          />
          <RangePicker value={range} onChange={handleRangeChange} allowClear={false} />
        </div>
      </div>

      <Spin spinning={loading}>
        {overview ? (
          <>
            {/* ── KPI 横幅 ── */}
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 14, marginBottom: 20,
            }}>
              {([
                {
                  label: `总能耗${kpi.activeMeta ? ` · ${kpi.activeMeta.display_name}` : ''}`,
                  value: kpi.total.toLocaleString('zh-CN', { maximumFractionDigits: 0 }),
                  suffix: kpi.unit, color: kpi.activeMeta?.color || '#5645d4', bg: '#f6f3ff',
                },
                {
                  label: `日均能耗${kpi.activeMeta ? ` · ${kpi.activeMeta.display_name}` : ''}`,
                  value: kpi.avg.toLocaleString('zh-CN', { maximumFractionDigits: 0 }),
                  suffix: kpi.unit, color: '#1677ff', bg: '#f0f5ff',
                },
                {
                  label: '环比变化',
                  value: `${kpi.pctChange >= 0 ? '+' : ''}${kpi.pctChange.toFixed(1)}%`,
                  suffix: '',
                  color: kpi.pctChange >= 0 ? '#e03131' : '#1aae39',
                  bg: kpi.pctChange >= 0 ? '#fff1f0' : '#f0fdf4',
                  icon: kpi.pctChange >= 0 ? '↑' : '↓',
                },
                { label: '峰值日', value: kpi.peakDay, suffix: '', color: '#dd5b00', bg: '#fff7e6' },
                { label: '最高车间', value: kpi.topWorkshop || '—', suffix: '', color: '#722ed1', bg: '#f9f0ff' },
              ] as const).map((item) => (
                <div key={item.label} style={{
                  background: item.bg, borderRadius: 12, padding: '16px 20px',
                  border: `1px solid ${item.color}15`,
                }}>
                  <div style={{ fontSize: 12, color: '#787671', marginBottom: 4 }}>{item.label}</div>
                  <div style={{ fontSize: 24, fontWeight: 600, color: item.color, lineHeight: 1.2 }}>
                    {'icon' in item ? <span style={{ marginRight: 4 }}>{item.icon}</span> : null}
                    {item.value}
                    <span style={{ fontSize: 12, fontWeight: 400, marginLeft: 3, color: '#a4a097' }}>{item.suffix}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* ── 能源类型选择器 ── */}
            <div style={{
              display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20,
              alignItems: 'center',
            }}>
              <button
                onClick={() => setSelectedType(null)}
                style={{
                  padding: '8px 18px', borderRadius: 20, cursor: 'pointer', fontSize: 13, fontWeight: 500,
                  border: !selectedType ? '2px solid #5645d4' : '1px solid #e8e3f0',
                  background: !selectedType ? '#f6f3ff' : '#fff',
                  color: !selectedType ? '#5645d4' : '#787671',
                  transition: 'all 0.2s',
                }}
              >
                全部能源
              </button>
              {metadata.map((m) => {
                const k = `total_${m.type_code}`
                const tv = (overview.summary[k] as number) ?? (overview.summary[m.type_code] as number) ?? 0
                const active = selectedType === m.type_code
                return (
                  <button
                    key={m.type_code}
                    onClick={() => setSelectedType(active ? null : m.type_code)}
                    style={{
                      padding: '8px 16px', borderRadius: 20, cursor: 'pointer', fontSize: 13,
                      border: active ? `2px solid ${m.color || '#1677ff'}` : '1px solid #e8e3f0',
                      background: active ? `${m.color}12` || '#f0f5ff' : '#fff',
                      color: active ? (m.color || '#1677ff') : '#37352f',
                      transition: 'all 0.2s',
                      display: 'flex', alignItems: 'center', gap: 8,
                    }}
                  >
                    <span style={{
                      width: 10, height: 10, borderRadius: '50%',
                      background: m.color || '#999', display: 'inline-block',
                    }} />
                    <span style={{ fontWeight: active ? 600 : 400 }}>{m.display_name}</span>
                    <span style={{ color: active ? 'inherit' : '#a4a097', opacity: active ? 1 : 0.8 }}>
                      {tv.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} {m.unit}
                    </span>
                  </button>
                )
              })}
            </div>

            {/* ── 堆叠面积图 ── */}
            <div style={{
              background: '#fff', borderRadius: 12, padding: '20px 24px', marginBottom: 20,
              border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}>
              <div style={{ fontSize: 16, fontWeight: 500, color: '#1a1a1a', marginBottom: 4 }}>
                {selectedType
                  ? `${metadata.find((m) => m.type_code === selectedType)?.display_name || '能耗'} 趋势`
                  : '能耗趋势对比'}
                {!selectedType && metadata.length > 1 && (
                  <span style={{ fontSize: 12, fontWeight: 400, color: '#a4a097', marginLeft: 8 }}>
                    多系列折线 · 点击图例筛选
                  </span>
                )}
              </div>
              {areaData.length > 0 ? <Line {...lineConfig} /> : <Empty description="暂无趋势" style={{ padding: '40px 0' }} />}
            </div>

            {/* ── 车间排名 + 矩形树图 ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
              {/* 车间排名表 */}
              <div style={{
                background: '#fff', borderRadius: 12, padding: '20px 24px',
                border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}>
                <div style={{ fontSize: 16, fontWeight: 500, color: '#1a1a1a', marginBottom: 12 }}>
                  车间用量排名
                  {selectedType && (
                    <span style={{ fontSize: 12, fontWeight: 400, color: metadata.find((m) => m.type_code === selectedType)?.color || '#1677ff', marginLeft: 8 }}>
                      · {metadata.find((m) => m.type_code === selectedType)?.display_name}
                    </span>
                  )}
                  <span style={{ fontSize: 12, fontWeight: 400, color: '#a4a097', marginLeft: 8 }}>
                    点击行查看区域
                  </span>
                </div>
                {workshopData.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {workshopData.map((w, i) => {
                      const pct = maxWs > 0 ? (w.value / maxWs) * 100 : 0
                      const active = selectedWorkshop === w.workshop
                      return (
                        <div
                          key={w.workshop}
                          onClick={() => setSelectedWorkshop(active ? null : w.workshop)}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 10, padding: '6px 10px',
                            borderRadius: 8, cursor: 'pointer',
                            background: active ? '#f6f3ff' : 'transparent',
                            border: active ? '1px solid #e8e3f0' : '1px solid transparent',
                            transition: 'all 0.15s',
                          }}
                        >
                          <span style={{
                            width: 22, height: 22, borderRadius: 6,
                            background: i < 3 ? '#5645d4' : '#c8c4be',
                            color: '#fff', fontSize: 11, fontWeight: 600,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            flexShrink: 0,
                          }}>
                            {i + 1}
                          </span>
                          <span style={{ width: 80, fontSize: 13, fontWeight: 500, color: '#37352f', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {w.workshop}
                          </span>
                          <div style={{ flex: 1, height: 8, background: '#f0f0f0', borderRadius: 4, overflow: 'hidden' }}>
                            <div style={{
                              height: '100%', width: `${pct}%`,
                              background: `linear-gradient(90deg, ${i < 3 ? '#5645d4' : '#a4a097'}, ${i < 3 ? '#8b7cf0' : '#c8c4be'})`,
                              borderRadius: 4, transition: 'width 0.4s',
                            }} />
                          </div>
                          <span style={{ width: 70, textAlign: 'right', fontSize: 13, fontWeight: 500, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
                            {w.value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ) : <Empty description="暂无数据" style={{ padding: '40px 0' }} />}
              </div>

              {/* 区域分布分组条形图 */}
              <div style={{
                background: '#fff', borderRadius: 12, padding: '20px 24px',
                border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}>
                <div style={{ fontSize: 16, fontWeight: 500, color: '#1a1a1a', marginBottom: 8 }}>
                  区域用量分布
                  {selectedWorkshop && (
                    <span style={{ fontSize: 13, fontWeight: 400, color: '#5645d4', marginLeft: 8 }}>
                      › {selectedWorkshop}
                    </span>
                  )}
                </div>
                {plBarData.length > 0 ? (
                  <Bar {...plBarConfig} />
                ) : (
                  <Empty description={selectedWorkshop ? '该车间暂无区域数据' : '暂无区域数据'} style={{ padding: '40px 0' }} />
                )}
              </div>
            </div>

            {/* ── 能源类型明细表 ── */}
            <div style={{
              background: '#fff', borderRadius: 12, padding: '20px 24px',
              border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}>
              <div style={{ fontSize: 16, fontWeight: 500, color: '#1a1a1a', marginBottom: 12 }}>
                能源类型明细
              </div>
              <Table
                columns={detailColumns}
                dataSource={detailData}
                pagination={false}
                size="small"
                style={{ marginTop: -8 }}
              />
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}>
            <Empty description="暂无数据" />
          </div>
        )}
      </Spin>
    </div>
  )
}
