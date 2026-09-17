'use client'

import * as echarts from 'echarts'
import ReactECharts from 'echarts-for-react'
import type { CSSProperties } from 'react'
import { EmptyGuide } from './EmptyGuide'

/**
 * 仓储统一 echarts 主题与图表封装（UI 底座）。
 * 主题一次注册，全部仓储图表走 'warehouse' 主题：配色对齐全局 token、
 * 弱化网格、渐变面积、空数据渲染引导空态而非裸坐标轴。
 */

// canvas 无法读 CSS 变量，具体色值取 tokens.ts 的 TONE_HEX（与 globals.css --wh-* 同源）
import { TONE_HEX } from './tokens'

const WH = {
  primary: TONE_HEX.primary,
  primarySoft: '#9a8de2',
  ok: TONE_HEX.ok,
  warn: TONE_HEX.warn,
  danger: TONE_HEX.danger,
  info: TONE_HEX.info,
  axisLabel: '#787671',
  axisLine: '#e5e3df',
  splitLine: '#f0eeeb',
}

let themeRegistered = false

export function ensureWarehouseTheme() {
  if (themeRegistered || typeof window === 'undefined') return
  echarts.registerTheme('warehouse', {
    color: [WH.primary, WH.info, WH.ok, WH.warn, WH.danger, WH.primarySoft],
    textStyle: { fontFamily: "Inter, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif" },
    title: { textStyle: { fontSize: 13, fontWeight: 600, color: '#37352f' } },
    legend: {
      itemWidth: 8,
      itemHeight: 8,
      icon: 'circle',
      textStyle: { color: WH.axisLabel, fontSize: 12 },
    },
    tooltip: {
      borderWidth: 0,
      backgroundColor: 'rgba(26,26,26,0.92)',
      textStyle: { color: '#fff', fontSize: 12 },
      extraCssText: 'border-radius:8px;padding:8px 12px;box-shadow:0 6px 16px rgba(16,24,40,0.18);',
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: WH.axisLine } },
      axisTick: { show: false },
      axisLabel: { color: WH.axisLabel, fontSize: 12 },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: WH.axisLabel, fontSize: 12 },
      splitLine: { lineStyle: { color: WH.splitLine } },
    },
    line: { smooth: true, symbolSize: 0, lineWidth: 2.5 },
    bar: { barMaxWidth: 22, itemStyle: { borderRadius: [4, 4, 0, 0] } },
    pie: { itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 } },
  })
  themeRegistered = true
}

function hasData(series: number[][]): boolean {
  return series.some(values => values.some(v => Number(v) > 0))
}

function ChartEmpty({ height, text }: { height: number | string; text: string }) {
  return (
    <div style={{ height }} className="flex items-center justify-center">
      <EmptyGuide compact title={text} />
    </div>
  )
}

/** 出入库趋势双系列面积图；全零数据时显示空态引导而非 0-1 裸轴 */
export function TrendAreaChart({
  dates,
  inbound,
  outbound,
  height = 260,
  emptyText = '近期暂无出入库',
}: {
  dates: string[]
  inbound: number[]
  outbound: number[]
  /** 像素高度，或 '100%' 让图表随容器（flex-1 卡片体）自适应 */
  height?: number | string
  emptyText?: string
}) {
  ensureWarehouseTheme()
  if (!hasData([inbound, outbound])) return <ChartEmpty height={height} text={emptyText} />
  const areaStyle = (from: string, to: string) => ({
    opacity: 0.9,
    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: from },
      { offset: 1, color: to },
    ]),
  })
  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['入库', '出库'], right: 8, top: 0 },
    grid: { left: 44, right: 16, top: 32, bottom: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: dates },
    yAxis: { type: 'value' },
    series: [
      {
        name: '入库',
        type: 'line',
        data: inbound,
        lineStyle: { color: WH.ok },
        itemStyle: { color: WH.ok },
        areaStyle: areaStyle('rgba(26,174,57,0.22)', 'rgba(26,174,57,0.02)'),
      },
      {
        name: '出库',
        type: 'line',
        data: outbound,
        lineStyle: { color: WH.danger },
        itemStyle: { color: WH.danger },
        areaStyle: areaStyle('rgba(224,49,49,0.18)', 'rgba(224,49,49,0.02)'),
      },
    ],
  }
  return <ReactECharts option={option} style={{ height } as CSSProperties} theme="warehouse" notMerge />
}

/** 分类占比环形图：中心显示总量，统一顺序色环 */
export function DonutChart({
  items,
  height = 240,
  centerLabel = '总量',
  emptyText = '暂无分布数据',
}: {
  items: { name: string; value: number }[]
  height?: number
  centerLabel?: string
  emptyText?: string
}) {
  ensureWarehouseTheme()
  const total = items.reduce((acc, it) => acc + Number(it.value || 0), 0)
  if (total <= 0) return <ChartEmpty height={height} text={emptyText} />
  const option = {
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', right: 8, top: 'center', textStyle: { fontSize: 12 } },
    title: {
      text: String(total),
      subtext: centerLabel,
      left: '38%',
      top: '42%',
      textAlign: 'center',
      textStyle: { fontSize: 22, fontWeight: 700, color: '#1a1a1a' },
      subtextStyle: { fontSize: 12, color: WH.axisLabel },
    },
    series: [
      {
        type: 'pie',
        radius: ['58%', '82%'],
        center: ['40%', '50%'],
        label: { show: false },
        data: items,
      },
    ],
  }
  return <ReactECharts option={option} style={{ height } as CSSProperties} theme="warehouse" notMerge />
}

/** 横向条形排行（低库存/呆滞 Top 等），支持点击下钻 */
export function RankBarChart({
  names,
  values,
  height = 240,
  color = WH.primary,
  onPick,
  emptyText = '暂无数据',
}: {
  names: string[]
  values: number[]
  height?: number
  color?: string
  onPick?: (name: string) => void
  emptyText?: string
}) {
  ensureWarehouseTheme()
  if (!hasData([values])) return <ChartEmpty height={height} text={emptyText} />
  const option = {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      inverse: true,
      data: names,
      axisLabel: { width: 110, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 16,
        data: values,
        itemStyle: { borderRadius: [0, 4, 4, 0], color },
        label: { show: true, position: 'right', fontSize: 12, color: WH.axisLabel },
      },
    ],
  }
  return (
    <ReactECharts
      option={option}
      style={{ height } as CSSProperties}
      theme="warehouse"
      notMerge
      onEvents={onPick ? { click: (params: { name: string }) => onPick(params.name) } : undefined}
    />
  )
}
