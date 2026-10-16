'use client'

import * as echarts from 'echarts'
import ReactECharts from 'echarts-for-react'
import { useEffect, useRef, type CSSProperties } from 'react'
import { EmptyGuide } from './EmptyGuide'

/**
 * 仓库级统一 echarts 主题与图表封装（ui-kit）。
 * 主题一次注册，全部套件图表走 'warehouse' 主题（历史主题名）：配色对齐全局 token、
 * 弱化网格、渐变面积、空数据渲染引导空态而非裸坐标轴。
 */

// canvas 无法读 CSS 变量，具体色值取 tokens.ts 的 TONE_HEX（与 globals.css --wh-* 同源）
import { TONE_HEX } from './tokens'

/** 双序列图可用色 tone（TONE_HEX 的键） */
export type ChartTone = keyof typeof TONE_HEX

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

/** #rrggbb → rgba(...)（渐变面积透明度用，canvas 场景无法读 CSS 变量） */
function hexRgba(hex: string, alpha: number): string {
  const n = Number.parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r},${g},${b},${alpha})`
}

/** 双序列趋势面积图（A/B 各配标签与语义色）；全零数据时显示空态引导而非 0-1 裸轴 */
export function TrendAreaChart({
  dates,
  seriesA,
  seriesB,
  labelA,
  labelB,
  toneA = 'ok',
  toneB = 'danger',
  height = 260,
  emptyText = '近期暂无数据',
}: {
  dates: string[]
  seriesA: number[]
  seriesB: number[]
  labelA: string
  labelB: string
  toneA?: ChartTone
  toneB?: ChartTone
  /** 像素高度，或 '100%' 让图表随容器（flex-1 卡片体）自适应 */
  height?: number | string
  emptyText?: string
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ReactECharts>(null)
  const empty = !hasData([seriesA, seriesB])

  // 卡片被 Row 等高拉伸时 echarts 实例不跟随容器尺寸，canvas 停在初始小尺寸
  // （表现为图表压在顶部、下方大片空白、Y 轴刻度重叠）——用 ResizeObserver 补 resize。
  // 首轮回调跳过：echarts 初始化时已按容器尺寸渲染，挂载瞬间再 resize 会与其内部渲染竞态
  useEffect(() => {
    const wrap = wrapRef.current
    if (empty || !wrap || typeof ResizeObserver === 'undefined') return
    let lastW = wrap.clientWidth
    let lastH = wrap.clientHeight
    const ro = new ResizeObserver(entries => {
      const rect = entries[entries.length - 1].contentRect
      if (rect.width === lastW && rect.height === lastH) return
      lastW = rect.width
      lastH = rect.height
      const chart = chartRef.current?.getEchartsInstance()
      // 实例可能在 React 重挂载间隙被 dispose；竞态下 resize 抛错则静默跳过，等下次触发
      if (!chart || chart.isDisposed()) return
      try {
        chart.resize()
      } catch {
        /* 下一次尺寸变化会再触发 */
      }
    })
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [empty])

  ensureWarehouseTheme()
  if (empty) return <ChartEmpty height={height} text={emptyText} />
  const areaStyle = (from: string, to: string) => ({
    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: from },
      { offset: 1, color: to },
    ]),
  })
  const colorA = TONE_HEX[toneA]
  const colorB = TONE_HEX[toneB]
  const line = (color: string, data: number[], name: string, areaFrom: number) => ({
    name,
    type: 'line',
    data,
    smoothMonotone: 'x', // 单调插值：尖峰处样条不再向上过冲出假包络
    showSymbol: false, // 常态隐藏数据点，悬停/tooltip 高亮时浮现
    symbol: 'circle',
    symbolSize: 4.5,
    lineStyle: { color },
    itemStyle: { color },
    emphasis: { focus: 'series' },
    areaStyle: areaStyle(hexRgba(color, areaFrom), hexRgba(color, 0.02)),
  })
  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: [labelA, labelB], right: 8, top: 0 },
    // containLabel 保证 Y 轴刻度不被裁剪；top 留出图例行高度
    grid: { left: 8, right: 16, top: 36, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLabel: { showMaxLabel: true }, // 间隔抽稀时保证最新一天始终可见
    },
    yAxis: { type: 'value', minInterval: 1 }, // 计数场景刻度取整
    series: [
      line(colorA, seriesA, labelA, 0.18),
      line(colorB, seriesB, labelB, 0.14),
    ],
  }
  return (
    <div ref={wrapRef} style={{ height } as CSSProperties}>
      <ReactECharts
        ref={chartRef}
        option={option}
        style={{ height: '100%', width: '100%' }}
        theme="warehouse"
        notMerge
      />
    </div>
  )
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
