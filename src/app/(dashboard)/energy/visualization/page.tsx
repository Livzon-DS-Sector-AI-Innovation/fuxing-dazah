'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { Select, Spin, Empty, App, Segmented } from 'antd'
import { Column, Line } from '@ant-design/charts'
import { fetchVisualizationData } from '@/lib/api/energy'
import { energyTypeLabels } from '@/components/energy/constants'

const META_FIELDS = new Set(['日期', '数据类型', '各分表总和', '厂内总表之和', '外购电总表之和'])

const ENERGY_OPTIONS = Object.entries(energyTypeLabels).map(([value, { text }]) => ({ label: text, value }))

export default function VisualizationPage() {
  const { message } = App.useApp()
  const [energyType, setEnergyType] = useState('electricity')
  const [compareMode, setCompareMode] = useState<'day' | 'week' | 'month'>('day')
  const [barDayIndex, setBarDayIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [fields, setFields] = useState<any[]>([])
  const [records, setRecords] = useState<any[]>([])
  const isNaturalGas = energyType === 'natural_gas'

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchVisualizationData(energyType)
      const table = data?.[energyType]
      if (table) { setFields(table.fields || []); setRecords(table.records || []) }
      else { setFields([]); setRecords([]) }
    } catch { message.error('获取可视化数据失败') }
    finally { setLoading(false) }
  }, [energyType, message])

  useEffect(() => { fetchData() }, [fetchData])

  const numFields = useMemo(() => fields.filter((f: any) => f.type === 2 && !META_FIELDS.has(f.field_name)), [fields])

  // ── 仪表盘 ──
  const gaugeInfo = useMemo(() => {
    if (!records.length) return { pct: 0, yesterday: 0, dayBefore: 0, max: 1 }
    const sorted = [...records].sort((a, b) => (b.fields['日期'] || 0) - (a.fields['日期'] || 0))
    const sum = (r: any) => numFields.reduce((s, f) => s + (parseFloat(String(r.fields[f.field_name] ?? 0)) || 0), 0)
    const yesterday = sorted.length > 1 ? sum(sorted[1]) : 0
    const dayBefore = sorted.length > 2 ? sum(sorted[2]) : 0
    const max = Math.max(...sorted.map(sum).filter((v) => !isNaN(v)), 1)
    return { pct: max > 0 ? Math.round((yesterday / max) * 100) / 100 : 0, yesterday: yesterday || 0, dayBefore: dayBefore || 0, max }
  }, [records, numFields])

  // ── 柱状图 ──
  const barData = useMemo(() => {
    if (!records.length) return []
    const sorted = [...records].sort((a, b) => (b.fields['日期'] || 0) - (a.fields['日期'] || 0))
    const target = sorted[Math.min(barDayIndex, sorted.length - 1)].fields
    return numFields
      .map((f: any) => ({ department: f.field_name, value: parseFloat(String(target[f.field_name] ?? 0)) }))
      .filter((d) => d.value > 0)
      .sort((a, b) => b.value - a.value)
  }, [records, numFields, barDayIndex])

  const barConfig = { data: barData, xField: 'department', yField: 'value', scale: { y: { nice: true } }, axis: { x: { labelAutoRotate: true, labelFontSize: 11 }, y: { labelFontSize: 11 } }, style: { radiusTopLeft: 6, radiusTopRight: 6 }, colorField: 'department', color: ['#5645d4', '#0075de', '#1aae39', '#dd5b00', '#722ed1', '#2f54eb', '#fa541c', '#faad14', '#eb2f96', '#52c41a', '#13c2c2', '#f5222d', '#1890ff'], legend: false, tooltip: { items: [(d: any) => ({ name: '用量', value: d.value.toFixed(2) })] } }

  // ── 天然气折线图 ──
  const lineData = useMemo(() => {
    if (!isNaturalGas || !records.length) return []
    const sorted = [...records].sort((a, b) => (a.fields['日期'] || 0) - (b.fields['日期'] || 0))
    return sorted.slice(-10).map((r) => ({
      date: new Date(r.fields['日期']).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }),
      value: numFields.reduce((s, f) => s + parseFloat(String(r.fields[f.field_name] ?? 0)), 0),
    }))
  }, [records, numFields, isNaturalGas])

  const lineConfig = { data: lineData, xField: 'date', yField: 'value', scale: { y: { nice: true } }, axis: { x: { labelAutoRotate: true, labelFontSize: 11 }, y: { labelFontSize: 11 } }, point: { size: 4 }, style: { lineWidth: 2 }, color: '#faad14', tooltip: { items: [(d: any) => ({ name: '总用量', value: d.value.toFixed(2) })] } }

  // ── Top5 环比 ──
  const compareData = useMemo(() => {
    if (!records.length) return []
    const sorted = [...records].sort((a, b) => (a.fields['日期'] || 0) - (b.fields['日期'] || 0))
    const byDate = new Map<number, Map<string, number>>()
    for (const r of sorted) {
      const ts = r.fields['日期']; if (!byDate.has(ts)) byDate.set(ts, new Map())
      const day = byDate.get(ts)!
      for (const f of numFields) {
        const v = parseFloat(String(r.fields[f.field_name] ?? 0))
        day.set(f.field_name, (day.get(f.field_name) || 0) + v)
      }
    }
    const dates = [...byDate.keys()].sort((a, b) => a - b)
    if (dates.length < 2) return []

    let curDates: number[], prevDates: number[]
    if (compareMode === 'day') { curDates = [dates[dates.length - 1]]; prevDates = [dates[dates.length - 2]] }
    else if (compareMode === 'week') { curDates = dates.slice(-7); prevDates = dates.slice(-14, -7) }
    else {
      const byMonth = new Map<string, number[]>()
      for (const t of dates) {
        const d = new Date(t); const m = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
        if (!byMonth.has(m)) byMonth.set(m, []); byMonth.get(m)!.push(t)
      }
      const months = [...byMonth.keys()].sort()
      if (months.length < 2) return []
      curDates = byMonth.get(months[months.length - 1]) || []; prevDates = byMonth.get(months[months.length - 2]) || []
    }
    if (!curDates.length || !prevDates.length) return []

    const curSum = new Map<string, number>(), prevSum = new Map<string, number>()
    for (const f of numFields) {
      const fn = f.field_name
      curSum.set(fn, curDates.reduce((s, d) => s + (byDate.get(d)?.get(fn) || 0), 0))
      prevSum.set(fn, prevDates.reduce((s, d) => s + (byDate.get(d)?.get(fn) || 0), 0))
    }
    return [...curSum.entries()].filter(([, v]) => v > 0).map(([name, cur]) => {
      const prev = prevSum.get(name) || 0
      const rate = prev > 0 ? ((cur - prev) / prev) * 100 : cur > 0 ? 100 : 0
      return { name, cur, prev, rate }
    }).sort((a, b) => b.cur - a.cur).slice(0, 5)
  }, [records, numFields, compareMode])

  const filled = { background: '#f6f5f4', border: 'none', borderRadius: 8, height: 36 }

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1280, minHeight: '100%', background: '#fafaf9' }}>
      <h1 style={{ fontSize: 28, fontWeight: 500, color: '#1a1a1a', margin: 0, letterSpacing: '-0.3px' }}>可视化视图</h1>
      <p style={{ fontSize: 13, color: '#a4a097', margin: '4px 0 0' }}>从飞书多维表格拉取能耗数据，按部门与时间维度展示</p>
      <div style={{ height: 1, marginTop: 18, marginBottom: 20, background: 'linear-gradient(to right, #5645d4 0%, transparent 100%)' }} />

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', background: '#fff', borderRadius: 12, padding: '12px 18px', boxShadow: '0 1px 3px rgba(10,10,10,0.04)', border: '1px solid #ede9e4', marginBottom: 20 }}>
        <span style={{ fontSize: 13, color: '#5d5b54', fontWeight: 500 }}>能源类型</span>
        <Select value={energyType} onChange={setEnergyType} variant="filled" style={{ width: 150, ...filled }} options={ENERGY_OPTIONS} />
      </div>

      <Spin spinning={loading}>
        {records.length === 0 && !loading ? (
          <Empty description="暂无数据" />
        ) : (
          <div style={{ display: 'grid', gap: 16 }}>
            {/* 仪表盘 */}
            <div style={{ background: '#fff', borderRadius: 12, padding: '20px 24px', border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(10,10,10,0.04)' }}>
              <h3 style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', margin: '0 0 16px' }}>昨日总用量</h3>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 40 }}>
                <div style={{ position: 'relative', width: 180, height: 100, overflow: 'hidden' }}>
                  {/* 半圆背景 */}
                  <div style={{
                    width: 180, height: 90, borderRadius: '90px 90px 0 0',
                    background: 'conic-gradient(from 180deg, #1aae39 0deg, #faad14 90deg, #e03131 180deg)',
                  }} />
                  {/* 指针 */}
                  <div style={{
                    position: 'absolute', bottom: 0, left: '50%', width: 2, height: 70,
                    background: '#5645d4', borderRadius: 1,
                    transform: `rotate(${-90 + gaugeInfo.pct * 180}deg)`,
                    transformOrigin: 'bottom center',
                    transition: 'transform 0.5s ease',
                  }} />
                  {/* 中心圆 */}
                  <div style={{ position: 'absolute', bottom: -8, left: '50%', transform: 'translateX(-50%)', width: 12, height: 12, borderRadius: '50%', background: '#5645d4' }} />
                </div>
                <div>
                  <div style={{ fontSize: 32, fontWeight: 500, color: '#1a1a1a', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
                    {gaugeInfo.yesterday.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                  </div>
                  <div style={{ fontSize: 13, color: '#a4a097', marginTop: 4 }}>
                    前日 {gaugeInfo.dayBefore.toLocaleString()}
                    {gaugeInfo.dayBefore > 0 && (
                      <span style={{
                        color: gaugeInfo.yesterday >= gaugeInfo.dayBefore ? '#1aae39' : '#e03131',
                        fontWeight: 600, marginLeft: 8,
                      }}>
                        {gaugeInfo.yesterday >= gaugeInfo.dayBefore ? '↑' : '↓'} {Math.abs(Math.round((gaugeInfo.yesterday - gaugeInfo.dayBefore) / gaugeInfo.dayBefore * 100))}%
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {isNaturalGas ? (
              <div style={{ background: '#fff', borderRadius: 12, padding: '20px 24px', border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(10,10,10,0.04)' }}>
                <h3 style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', margin: '0 0 16px' }}>近十天趋势</h3>
                <Line {...lineConfig} height={400} />
              </div>
            ) : (
              <>
                <div style={{ background: '#fff', borderRadius: 12, padding: '20px 24px', border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(10,10,10,0.04)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                    <h3 style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>区域分布</h3>
                    <Segmented value={barDayIndex === 0 ? 'latest' : 'yesterday'} onChange={(v) => setBarDayIndex(v === 'latest' ? 0 : 1)} options={[{ label: '最新', value: 'latest' }, { label: '昨日', value: 'yesterday' }]} style={{ background: '#f6f5f4', borderRadius: 6, padding: 1 }} size="small" />
                  </div>
                  <Column {...barConfig} height={400} />
                </div>
                {compareData.length > 0 && (
                  <div style={{ background: '#fff', borderRadius: 12, padding: '20px 24px', border: '1px solid #ede9e4', boxShadow: '0 1px 3px rgba(10,10,10,0.04)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                      <h3 style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>Top5 部门环比</h3>
                      <Segmented value={compareMode} onChange={(v) => setCompareMode(v as any)} options={[{ label: '日环比', value: 'day' }, { label: '周环比', value: 'week' }, { label: '月环比', value: 'month' }]} style={{ background: '#f6f5f4', borderRadius: 8, padding: 2 }} />
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      {compareData.map((d, i) => {
                        const isUp = d.rate >= 0
                        return (
                          <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <span style={{ width: 20, fontSize: 13, fontWeight: 600, color: i < 3 ? '#5645d4' : '#a4a097' }}>{i + 1}</span>
                            <span style={{ width: 100, fontSize: 13, color: '#37352f', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</span>
                            <span style={{ width: 90, fontSize: 13, color: '#5d5b54', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{d.cur.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</span>
                            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8 }}>
                              <div style={{ height: 6, width: `${Math.min(Math.abs(d.rate), 100)}%`, maxWidth: 200, borderRadius: 3, background: isUp ? '#1aae39' : '#e03131', transition: 'width 0.3s' }} />
                              <span style={{ fontSize: 13, fontWeight: 600, color: isUp ? '#1aae39' : '#e03131', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>{isUp ? '+' : ''}{d.rate.toFixed(1)}%</span>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </Spin>
    </div>
  )
}
