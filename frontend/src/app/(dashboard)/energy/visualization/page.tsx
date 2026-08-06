'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { DatePicker, Segmented, Spin, Empty, App, Button } from 'antd'
import { Line, Bar, Pie } from '@ant-design/charts'
import { DownloadOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import * as XLSX from 'xlsx'
import { getEnergyOverview } from '@/actions/energy'
import { fetchPriceCategoryDistribution } from '@/lib/api/energy'
import { PricePeriodDrawer } from '@/components/energy/PricePeriodDrawer'
import type { EnergyOverview, EnergyTypeMeta, PriceCategoryDistribution } from '@/types/energy'

const { RangePicker } = DatePicker

const RANGE_PRESETS: Record<string, [dayjs.Dayjs, dayjs.Dayjs]> = {
  '昨天': [dayjs().subtract(1, 'day').startOf('day'), dayjs().subtract(1, 'day').endOf('day')],
  '7天': [dayjs().subtract(6, 'day').startOf('day'), dayjs().endOf('day')],
  '30天': [dayjs().subtract(29, 'day').startOf('day'), dayjs().endOf('day')],
  '本月': [dayjs().startOf('month'), dayjs().endOf('day')],
}

export default function VisualizationPage() {
  const { message } = App.useApp()
  const [range, setRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>(RANGE_PRESETS['7天'])
  const [activePreset, setActivePreset] = useState<string>('7天')
  const [selectedType, setSelectedType] = useState<string>('')
  const [selectedWorkshop, setSelectedWorkshop] = useState<string | null>(null)
  const [overview, setOverview] = useState<EnergyOverview | null>(null)
  const [prevOverview, setPrevOverview] = useState<EnergyOverview | null>(null)
  const [loading, setLoading] = useState(false)
  const [priceCategory, setPriceCategory] = useState<PriceCategoryDistribution | null>(null)
  const [periodDrawerOpen, setPeriodDrawerOpen] = useState(false)

  const days = range[1].diff(range[0], 'day') + 1

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = range[1].diff(range[0], 'day') + 1
      const [curr, prev] = await Promise.all([
        getEnergyOverview({
          start_time: range[0].toISOString(),
          end_time: range[1].toISOString(),
          granularity: 'daily',
          energy_type: selectedType || undefined,
        }),
        getEnergyOverview({
          start_time: range[0].subtract(d, 'day').toISOString(),
          end_time: range[1].subtract(d, 'day').toISOString(),
          granularity: 'daily',
          energy_type: selectedType || undefined,
        }),
      ])
      setOverview(curr)
      setPrevOverview(prev)

      // 峰谷分布（点部门时联动筛选）
      try {
        const pc = await fetchPriceCategoryDistribution({
          start_time: range[0].toISOString(),
          end_time: range[1].toISOString(),
          energy_type: selectedType || undefined,
          workshop: selectedWorkshop || undefined,
        })
        setPriceCategory(pc)
      } catch {
        setPriceCategory(null)
      }
    } catch {
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [range, selectedType, selectedWorkshop])

  useEffect(() => { load() }, [load])
  useEffect(() => { setSelectedWorkshop(null) }, [selectedType])

  const metadata = overview?.type_metadata || []

  // 首次加载时自动选中第一个能源类型
  useEffect(() => {
    if (!selectedType && metadata.length > 0) {
      setSelectedType(metadata[0].type_code)
    }
  }, [metadata, selectedType])

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

    // 最高部门（当前能源类型）
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

  // ── 部门排名 ──
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
    // 按部门分配颜色
    const colorMap: Record<string, string> = {}
    const uniqueWorkshops = [...new Set(plBarData.map((d) => d.workshop).filter((w) => w && w !== '未知'))]
    uniqueWorkshops.forEach((w, i) => { colorMap[w] = workshopColors[i % workshopColors.length] })

    return {
      data: plBarData.map((d) => ({
        ...d,
        label: d.workshop && d.workshop !== '未知' ? `${d.name}（${d.workshop}）` : d.name,
      })),
      xField: 'label',   // 转置后 x → 纵轴：区域名称
      yField: 'value',   // 转置后 y → 横轴：用量数值
      height: Math.max(220, Math.min(420, plBarData.length * 36)),
      barWidthRatio: 0.65,
      color: (d: Record<string, unknown>) => colorMap[d.workshop as string] || '#5645d4',
      label: {
        position: 'right' as const,
        text: (d: any) => `${(d.value ?? 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`,
        style: { fontSize: 11, fill: '#5d5b54', textAlign: 'start' },
        offset: 6,
      },
      yAxis: {
        label: {
          formatter: (v: string) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }),
        },
        grid: { line: { style: { stroke: '#f0f0f0', lineDash: [3, 3] } } },
      },
      xAxis: {
        label: { autoEllipsis: true, style: { fontSize: 11 } },
      },
    }
  }, [plBarData])

  // ── 导出 Excel ──
  const handleExport = useCallback(() => {
    if (!overview) return
    const wb = XLSX.utils.book_new()

    // Sheet 1: 趋势数据
    const trendRows = (overview.trend || []).map((t) => {
      const meta = metadata.find((m) => m.type_code === t.type)
      return {
        '日期': dayjs(t.time).format('YYYY-MM-DD'),
        '能源类型': meta?.display_name || t.type,
        '用量': t.value,
        '单位': meta?.unit || '',
      }
    })
    if (trendRows.length > 0) {
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(trendRows), '趋势数据')
    }

    // Sheet 2: 部门分布
    const wsRows = (overview.workshop_distribution || []).map((w) => ({
      '部门': w.group_key || '未知',
      '能源类型': metadata.find((m) => m.type_code === w.energy_type)?.display_name || w.energy_type,
      '用量': w.total_value,
      '单位': metadata.find((m) => m.type_code === w.energy_type)?.unit || '',
    }))
    if (wsRows.length > 0) {
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(wsRows), '部门分布')
    }

    // Sheet 3: 区域分布
    const plRows = (overview.production_line_distribution || []).map((p) => ({
      '区域': p.group_key || '未知',
      '部门': p.workshop || '未知',
      '能源类型': metadata.find((m) => m.type_code === p.energy_type)?.display_name || p.energy_type,
      '用量': p.total_value,
      '单位': metadata.find((m) => m.type_code === p.energy_type)?.unit || '',
    }))
    if (plRows.length > 0) {
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(plRows), '区域分布')
    }

    const filename = `能源分析_${range[0].format('YYYYMMDD')}-${range[1].format('YYYYMMDD')}.xlsx`
    XLSX.writeFile(wb, filename)
    message.success('导出成功')
  }, [overview, metadata, range])

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
          <Button icon={<DownloadOutlined />} onClick={handleExport} disabled={!overview}>
            导出 Excel
          </Button>
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
                { label: '最高部门', value: kpi.topWorkshop || '—', suffix: '', color: '#722ed1', bg: '#f9f0ff' },
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
              {metadata.map((m) => {
                const k = `total_${m.type_code}`
                const tv = (overview.summary[k] as number) ?? (overview.summary[m.type_code] as number) ?? 0
                const active = selectedType === m.type_code
                return (
                  <button
                    key={m.type_code}
                    onClick={() => setSelectedType(m.type_code)}
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
                {metadata.find((m) => m.type_code === selectedType)?.display_name || '能耗'} 趋势
              </div>
              {areaData.length > 0 ? <Line {...lineConfig} /> : <Empty description="暂无趋势" style={{ padding: '40px 0' }} />}
            </div>

            {/* ── 部门排名 + 矩形树图 ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
              {/* 部门排名表 */}
              <div style={{
                background: '#fff', borderRadius: 12, padding: '20px 24px',
                border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}>
                <div style={{ fontSize: 16, fontWeight: 500, color: '#1a1a1a', marginBottom: 12 }}>
                  部门用量排名
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
                  <Empty description={selectedWorkshop ? '该部门暂无区域数据' : '暂无区域数据'} style={{ padding: '40px 0' }} />
                )}
              </div>
            </div>

            {/* ── 峰谷用电分布 ── */}
            {priceCategory && priceCategory.categories.length > 0 && (
              <div style={{
                background: '#fff', borderRadius: 12, padding: '20px 24px', marginBottom: 20,
                border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}>
                <div style={{ fontSize: 16, fontWeight: 500, color: '#1a1a1a', marginBottom: 12 }}>
                  峰谷用电分布
                  <Button
                    type="link" size="small"
                    onClick={() => setPeriodDrawerOpen(true)}
                    style={{ fontSize: 11, padding: 0, marginLeft: 8 }}
                  >
                    配置规则
                  </Button>
                  {selectedWorkshop && (
                    <span style={{ fontSize: 13, fontWeight: 400, color: '#5645d4', marginLeft: 8 }}>
                      › {selectedWorkshop}
                    </span>
                  )}
                  <span style={{ fontSize: 12, fontWeight: 400, color: '#a4a097', marginLeft: 8 }}>
                    总 {priceCategory.total.toLocaleString('zh-CN', { maximumFractionDigits: 0 })} {priceCategory.unit}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'center' }}>
                  <Pie
                    data={priceCategory.categories.map((c) => ({
                      type: c.category,
                      value: c.total_value,
                    }))}
                    angleField="value"
                    colorField="type"
                    radius={0.8}
                    innerRadius={0.5}
                    height={300}
                    appendPadding={[10, 40, 40, 40]}
                    color={{ '尖': '#e03131', '峰': '#dd5b00', '平': '#1677ff', '谷': '#1aae39' }}
                    label={{
                      text: (d: { type: string; value: number }) => {
                        const item = priceCategory.categories.find((c2) => c2.category === d.type)
                        return `${d.type}\n${item?.percentage ?? 0}%`
                      },
                      position: 'outside',
                      style: { fontSize: 12, fontWeight: 500, fill: '#37352f' },
                      connector: { style: { stroke: '#c8c4be', lineWidth: 1 } },
                    }}
                    legend={false}
                    tooltip={{}}
                    statistic={{
                      title: { style: { fontSize: 13, color: '#a4a097' }, content: '总用电' },
                      content: {
                        style: { fontSize: 18, fontWeight: 600, color: '#37352f' },
                        content: priceCategory.total.toLocaleString('zh-CN', { maximumFractionDigits: 0 }),
                      },
                    }}
                    animate={{ appear: { animation: 'wave-in', duration: 600 } }}
                  />
                  {/* 分类明细 */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {priceCategory.categories.map((c) => {
                      const catColors: Record<string, string> = {
                        '尖': '#e03131', '峰': '#dd5b00', '平': '#1677ff', '谷': '#1aae39',
                      }
                      const labels: Record<string, string> = { '尖': '尖峰', '峰': '高峰', '平': '平段', '谷': '低谷' }
                      return (
                        <div key={c.category} style={{
                          display: 'flex', alignItems: 'center', gap: 10,
                          padding: '8px 12px', borderRadius: 8, background: '#fafaf9',
                        }}>
                          <span style={{
                            width: 12, height: 12, borderRadius: 3,
                            background: catColors[c.category] || '#999', flexShrink: 0,
                          }} />
                          <span style={{ fontSize: 14, fontWeight: 500, color: '#37352f', minWidth: 36 }}>
                            {labels[c.category] || c.category}
                          </span>
                          <span style={{ flex: 1, fontSize: 13, color: '#a4a097' }}>
                            {c.percentage}%
                          </span>
                          <span style={{ fontSize: 14, fontWeight: 600, color: '#37352f', fontVariantNumeric: 'tabular-nums' }}>
                            {c.total_value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                            <span style={{ fontSize: 11, fontWeight: 400, color: '#a4a097', marginLeft: 2 }}>{c.unit}</span>
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}
          </>
        ) : (
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}>
            <Empty description="暂无数据" />
          </div>
        )}
      </Spin>
      <PricePeriodDrawer open={periodDrawerOpen} onClose={() => { setPeriodDrawerOpen(false); load() }} />
    </div>
  )
}
