'use client'

import { useState, useEffect, useCallback, useRef, useMemo, type ReactNode } from 'react'
import { App, Card, Row, Col, Segmented, Button, Modal, Empty, Skeleton, DatePicker } from 'antd'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import {
  UserDeleteOutlined,
  HolderOutlined, PlusOutlined, CloseOutlined, DownOutlined,
  PieChartOutlined, BarChartOutlined, ClockCircleOutlined, EditOutlined,
  SafetyCertificateOutlined, FieldTimeOutlined, RiseOutlined, AlertOutlined, ApartmentOutlined, ExclamationCircleOutlined, WarningOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchDashboardStats } from '@/actions/hr'
import type { DashboardStats, DistributionItem, MonthlyByDeptItem, MonthlyByCategoryItem, MonthlyItem, MonthlyComparisonItem } from '@/types/hr'

type ChartType = 'pie' | 'bar'

// ═══════════════════════════════════════════════════════════════
// 设计令牌（对齐看板设计稿：飞书蓝系 + 浅蓝画布）
// ═══════════════════════════════════════════════════════════════
const T = {
  primary: '#1677FF',
  canvas: '#ffffff',
  pageBg: '#EBF2FB',
  surface: '#eef4fd',
  ink: '#1a1a1a',
  charcoal: '#303133',
  slate: '#5e6a7f',
  steel: '#7c8698',
  stone: '#a3adbf',
  muted: '#bcc5d3',
  hairline: '#e3e9f2',
  hairlineStrong: '#c6d3e6',
  hairlineSoft: '#edf2f9',
  success: '#1aae39',
  error: '#e03131',
  blue: '#1677FF',
} as const

const PALETTE = ['#1677FF', '#40A9FF', '#13c2c2', '#1aae39', '#fa8c16', '#722ed1', '#fadb14', '#e03131', '#ff85c0', '#002e8c']

const DEFAULT_H = 350; const MIN_H = 200; const MAX_H = 900; const SNAP_X = 80
// 默认布局对齐设计稿：人口结构 3 卡 → 部门分析 2 卡 → 年度入离职 2 卡 → 入离职对比折线 → 月度明细分组 2 卡
const PRESET_IDS = [
  'gender', 'age-overview', 'education', 'dept-ranking', 'department',
  'departures-by-dept', 'hires-by-dept-year', 'hire-departure-trend',
  'monthly-departures-by-category', 'monthly-hires-by-category',
]

// 宽度档位（12 列网格）：4=1/3 宽、6=半宽、8=2/3 宽、12=全宽
const WIDTH_TIERS = [4, 6, 8, 12] as const
const DEFAULT_PRESET_WIDTHS: Record<string, number> = {
  gender: 4, 'age-overview': 4, education: 4,
  'dept-ranking': 4, department: 8,
  'departures-by-dept': 6, 'hires-by-dept-year': 6, 'hire-departure-trend': 12,
  'monthly-departures-by-category': 6, 'monthly-hires-by-category': 6,
}
const WIDTH_LABELS: Record<number, string> = { 4: '1/3宽', 6: '半宽', 8: '2/3宽', 12: '全宽' }
const SPAN_CLASS: Record<number, string> = { 4: 'md:col-span-4', 6: 'md:col-span-6', 8: 'md:col-span-8', 12: 'md:col-span-12' }
// 自定义渲染卡片（折线对比 / 年龄复合卡）：不提供饼柱切换
const CUSTOM_RENDER_IDS = ['age-overview', 'hire-departure-trend']

interface StatTypeOption { id: string; title: string; defaultType: ChartType; group: string; dataSource: string }

const ALL_STAT_TYPES: StatTypeOption[] = [
  { id: 'gender', title: '在职员工男女比例', defaultType: 'pie', group: '人员结构', dataSource: 'gender' },
  { id: 'age-overview', title: '平均年龄与年龄分布', defaultType: 'bar', group: '人员结构', dataSource: 'age' },
  { id: 'education', title: '学历分布', defaultType: 'pie', group: '人员结构', dataSource: 'preset' },
  { id: 'dept-ranking', title: '部门人数排行TOP10', defaultType: 'bar', group: '人员结构', dataSource: 'preset' },
  { id: 'department', title: '部门人数分布', defaultType: 'bar', group: '人员结构', dataSource: 'preset' },
  { id: 'departures-by-dept', title: '本年度离职各部门', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'hires-by-dept-year', title: '本年度入职各部门', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'hire-departure-trend', title: '入离职月度对比', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'monthly-departures-by-category', title: '每月离职人数（按员工性质）', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'monthly-hires-by-category', title: '月入职人数（按员工性质）', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'hires-by-dept', title: '入职各部门月度统计', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'monthly-hires', title: '每月入职人数', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'monthly-departures', title: '离职月度统计', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'departure-comparison', title: '离职月度对比', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'age', title: '年龄区间分布', defaultType: 'bar', group: '人员结构', dataSource: 'age' },
  { id: 'level', title: '职级分布', defaultType: 'pie', group: '人员结构', dataSource: 'level' },
  { id: 'position', title: '岗位分布', defaultType: 'bar', group: '人员结构', dataSource: 'position' },
  { id: 'job_category', title: '职类分布', defaultType: 'pie', group: '人员结构', dataSource: 'job_category' },
  { id: 'hr_analysis', title: '人力资源分析分布', defaultType: 'pie', group: '人员结构', dataSource: 'hr_analysis' },
  { id: 'political_status', title: '政治面貌分布', defaultType: 'pie', group: '人员结构', dataSource: 'political_status' },
  { id: 'contract_type', title: '合同类型分布', defaultType: 'pie', group: '人员结构', dataSource: 'contract_type' },
  { id: 'tenure', title: '司龄分布', defaultType: 'bar', group: '人员结构', dataSource: 'tenure' },
  { id: 'departure-type', title: '离职类型分布', defaultType: 'pie', group: '离职分析', dataSource: 'departure_type' },
  { id: 'departure-reason', title: '离职原因分布', defaultType: 'pie', group: '离职分析', dataSource: 'departure_reason' },
  { id: 'departure-tenure', title: '离职司龄分布', defaultType: 'bar', group: '离职分析', dataSource: 'departure_tenure' },
  { id: 'position-departure-top', title: '岗位离职TOP10', defaultType: 'bar', group: '离职分析', dataSource: 'preset' },
  { id: 'dept-departure-rate', title: '各部门离职率(%)', defaultType: 'bar', group: '离职分析', dataSource: 'dept_departure_rate' },
  { id: 'monthly-departure-rate', title: '月度离职率(%)', defaultType: 'bar', group: '离职分析', dataSource: 'monthly_departure_rate' },
  { id: 'contract-expiry', title: '合同到期预警', defaultType: 'bar', group: '用工风险', dataSource: 'preset' },
  { id: 'retention', title: '新员工留存率(%)', defaultType: 'bar', group: '招聘', dataSource: 'retention' },
  { id: 'performance-grade', title: '绩效等级分布', defaultType: 'pie', group: '绩效', dataSource: 'performance_grade' },
]

const STAT_TYPE_MAP: Record<string, StatTypeOption> = Object.fromEntries(ALL_STAT_TYPES.map(s => [s.id, s]))

const LS_ORDER = 'hr_db_v4_order'; const LS_TYPES = 'hr_db_v4_types'
const LS_HEIGHTS = 'hr_db_v4_heights'; const LS_WIDTHS = 'hr_db_v4_widths'

function loadLS<T>(k: string, fb: T): T {
  if (typeof window === 'undefined') return fb
  try { const r = localStorage.getItem(k); return r ? JSON.parse(r) : fb } catch { return fb }
}
function saveLS(k: string, v: unknown) {
  if (typeof window === 'undefined') return
  try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* */ }
}

// ═══════════════════════════════════════════════════════════════
// CountUp hook — 数字滚动
// ═══════════════════════════════════════════════════════════════
function useCountUp(end: number, duration = 1400) {
  const [val, setVal] = useState(0)
  useEffect(() => {
    if (end === 0) { setVal(0); return }
    let frame: number; const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min((now - t0) / duration, 1)
      setVal(Math.round((1 - Math.pow(1 - p, 3)) * end)) // easeOutCubic
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [end, duration])
  return val
}

// ═══════════════════════════════════════════════════════════════
// ECharts 构建函数
// ═══════════════════════════════════════════════════════════════
const ECHART_TEXT_STYLE = { color: T.slate, fontSize: 12 }
const ECHART_AXIS_LABEL = { color: T.steel, fontSize: 11 }
const ECHART_SPLIT_LINE = { lineStyle: { color: T.hairlineSoft } }

function linearGradient(top: string, bottom: string) {
  return { type: 'linear' as const, x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: top }, { offset: 1, color: bottom }] }
}

const BASE_TOOLTIP = {
  backgroundColor: '#fff',
  borderColor: T.hairline,
  borderWidth: 1,
  textStyle: { color: T.charcoal, fontSize: 13 },
  extraCssText: 'border-radius:8px;box-shadow:0 4px 16px rgba(15,15,15,0.1);padding:10px 14px;',
}

function buildPieOption(data: DistributionItem[], colorMap?: Record<string, string>): EChartsOption {
  return {
    color: PALETTE,
    animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'item' as const, formatter: '<b>{b}</b><br/>人数: {c} 人 ({d}%)' },
    legend: { top: 0, textStyle: { ...ECHART_TEXT_STYLE, fontSize: 11 }, itemWidth: 10, itemHeight: 10, itemGap: 12 },
    series: [{
      type: 'pie' as const, radius: ['40%', '68%'], center: ['50%', '58%'], avoidLabelOverlap: true,
      itemStyle: { borderColor: T.canvas, borderWidth: 2 },
      data: data.map(d => ({ name: d.name, value: d.value, itemStyle: colorMap?.[d.name] ? { color: colorMap[d.name] } : undefined })),
      // 对齐设计稿：引出线外标签「类别: 数量 (百分比)」
      label: {
        show: true, position: 'outside' as const,
        formatter: '{b}: {c} ({d}%)',
        color: T.slate, fontSize: 11, lineHeight: 16,
      },
      labelLine: { show: true, length: 12, length2: 10, lineStyle: { color: T.muted } },
      emphasis: { scaleSize: 6 },
    }],
  }
}

function buildBarOption(names: string[], values: number[], color: string): EChartsOption {
  return {
    animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const },
    grid: { left: 48, right: 20, top: 20, bottom: names.length > 6 ? 48 : 32 },
    xAxis: {
      type: 'category' as const, data: names,
      axisLabel: { ...ECHART_AXIS_LABEL, rotate: names.length > 6 ? 35 : 0 },
      axisTick: { show: false }, axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value' as const, axisLabel: { ...ECHART_AXIS_LABEL, formatter: '{value}' },
      splitLine: ECHART_SPLIT_LINE, axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar' as const, data: values, barWidth: '50%',
      itemStyle: { borderRadius: [6, 6, 0, 0], color: linearGradient(color, `${color}30`) },
      label: { show: true, position: 'top' as const, color: T.steel, fontSize: 11, fontWeight: 500 },
    }],
  }
}

function buildDistributionBarOption(data: DistributionItem[]): EChartsOption {
  return {
    animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const },
    grid: { left: 48, right: 20, top: 20, bottom: data.length > 6 ? 48 : 32 },
    xAxis: {
      type: 'category' as const, data: data.map(d => d.name),
      axisLabel: { ...ECHART_AXIS_LABEL, rotate: data.length > 6 ? 35 : 0 },
      axisTick: { show: false }, axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value' as const, axisLabel: ECHART_AXIS_LABEL,
      splitLine: ECHART_SPLIT_LINE, axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar' as const, data: data.map(d => d.value), barWidth: '50%',
      itemStyle: { borderRadius: [6, 6, 0, 0], color: linearGradient(PALETTE[0], `${PALETTE[0]}25`) },
      label: { show: true, position: 'top' as const, color: T.steel, fontSize: 11, fontWeight: 500 },
    }],
  }
}

function buildGroupedBarOption<K extends 'department' | 'category'>(
  data: Array<{ month: string; value: number } & Record<K, string>>,
  seriesKey: K,
): EChartsOption {
  const months = [...new Set(data.map(d => d.month))].sort()
  const seriesNames = [...new Set(data.map(d => d[seriesKey]))]
  return {
    color: PALETTE, animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const },
    grid: { left: 48, right: 20, top: 36, bottom: 32 },
    legend: { top: 0, textStyle: { ...ECHART_TEXT_STYLE, fontSize: 11 }, itemWidth: 10, itemHeight: 10, itemGap: 12 },
    xAxis: {
      type: 'category' as const, data: months,
      axisLabel: { ...ECHART_AXIS_LABEL, rotate: months.length > 6 ? 35 : 0 },
      axisTick: { show: false }, axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value' as const, axisLabel: ECHART_AXIS_LABEL,
      splitLine: ECHART_SPLIT_LINE, axisLine: { show: false }, axisTick: { show: false },
    },
    series: seriesNames.map(name => ({
      name, type: 'bar' as const, barGap: '30%' as const,
      data: months.map(m => data.find(d => d.month === m && d[seriesKey] === name)?.value || 0),
      itemStyle: { borderRadius: [6, 6, 0, 0] },
      label: { show: true, position: 'top' as const, fontSize: 10, color: T.steel },
    })),
  }
}

function buildComparisonOption(data: MonthlyComparisonItem[]): EChartsOption {
  return {
    color: [T.stone, PALETTE[0]], animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const },
    grid: { left: 48, right: 20, top: 20, bottom: 48 },
    legend: { bottom: 0, data: ['去年', '今年'], textStyle: { ...ECHART_TEXT_STYLE, fontSize: 11 }, itemWidth: 10, itemHeight: 10, itemGap: 12 },
    xAxis: {
      type: 'category' as const, data: data.map(d => d.label),
      axisLabel: ECHART_AXIS_LABEL,
      axisTick: { show: false }, axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value' as const, axisLabel: ECHART_AXIS_LABEL,
      splitLine: ECHART_SPLIT_LINE, axisLine: { show: false }, axisTick: { show: false },
    },
    series: [
      {
        name: '去年', type: 'bar' as const, barGap: '30%' as const,
        data: data.map(d => d.last_year),
        itemStyle: { borderRadius: [6, 6, 0, 0], color: linearGradient(T.stone, `${T.stone}25`) },
        label: { show: true, position: 'top' as const, fontSize: 11, color: T.stone, fontWeight: 500 },
      },
      {
        name: '今年', type: 'bar' as const,
        data: data.map(d => d.current_year),
        itemStyle: { borderRadius: [6, 6, 0, 0], color: linearGradient(PALETTE[0], `${PALETTE[0]}25`) },
        label: { show: true, position: 'top' as const, fontSize: 11, color: PALETTE[0], fontWeight: 500 },
      },
    ],
  }
}

function buildHorizontalBarOption(data: DistributionItem[], topN?: number): EChartsOption {
  const pool = topN ? [...data].sort((a, b) => b.value - a.value).slice(0, topN) : data
  const sorted = [...pool].sort((a, b) => a.value - b.value) // 小→大，底部→顶部
  return {
    color: [PALETTE[0]], animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const, formatter: '<b>{b}</b><br/>人数: {c} 人' },
    grid: { left: 4, right: 52, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value' as const, axisLabel: ECHART_AXIS_LABEL, splitLine: ECHART_SPLIT_LINE, axisLine: { show: false }, axisTick: { show: false } },
    yAxis: {
      type: 'category' as const, data: sorted.map(d => d.name), inverse: true,
      axisLabel: { ...ECHART_AXIS_LABEL, width: 100, overflow: 'truncate' as const },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar' as const, data: sorted.map(d => d.value), barWidth: '60%',
      itemStyle: { borderRadius: [0, 6, 6, 0], color: linearGradient(PALETTE[0], `${PALETTE[0]}25`) },
      label: { show: true, position: 'right' as const, color: T.steel, fontSize: 11, fontWeight: 500 },
    }],
  }
}

// 入离职月度对比折线（入职=蓝、离职=绿），月份取两边并集
function buildHireDepartureLineOption(hires: MonthlyItem[], departures: MonthlyItem[]): EChartsOption {
  const months = [...new Set([...hires, ...departures].map(d => d.month))].sort()
  const hireMap = new Map(hires.map(d => [d.month, d.value]))
  const depMap = new Map(departures.map(d => [d.month, d.value]))
  const lineStyle = (color: string) => ({
    itemStyle: { color },
    lineStyle: { width: 3, color },
  })
  return {
    animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const },
    grid: { left: 48, right: 24, top: 36, bottom: 32 },
    legend: { top: 0, data: ['入职数', '离职数'], textStyle: { ...ECHART_TEXT_STYLE, fontSize: 11 }, itemWidth: 10, itemHeight: 10, itemGap: 12 },
    xAxis: {
      type: 'category' as const, data: months.map(m => m.replace('-', '年') + '月'),
      boundaryGap: false,
      axisLabel: ECHART_AXIS_LABEL,
      axisTick: { show: false }, axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value' as const, axisLabel: ECHART_AXIS_LABEL,
      splitLine: ECHART_SPLIT_LINE, axisLine: { show: false }, axisTick: { show: false },
      // 峰值预留 15% 头部空间，避免最高点的折线/标签贴住绘图区上缘
      max: (value: { max: number }) => Math.ceil((value.max || 0) * 1.15),
    },
    series: [
      {
        name: '入职数', type: 'line' as const, smooth: true, symbolSize: 7,
        data: months.map(m => hireMap.get(m) ?? 0), ...lineStyle(T.primary),
        areaStyle: { color: linearGradient('rgba(22,119,255,0.16)', 'rgba(22,119,255,0)') },
      },
      {
        name: '离职数', type: 'line' as const, smooth: true, symbolSize: 7,
        data: months.map(m => depMap.get(m) ?? 0), ...lineStyle(T.success),
      },
    ],
  }
}

// 年龄分布简洁柱（无坐标轴、蓝色圆角柱 + 数值标签，用于「平均年龄与年龄分布」复合卡）
function buildAgeOverviewOption(data: DistributionItem[]): EChartsOption {
  return {
    animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const, formatter: '<b>{b}</b><br/>人数: {c} 人' },
    grid: { left: 12, right: 12, top: 24, bottom: 4, containLabel: false },
    xAxis: {
      type: 'category' as const, data: data.map(d => d.name),
      axisLabel: { ...ECHART_AXIS_LABEL, fontSize: 11 },
      axisTick: { show: false }, axisLine: { show: false },
    },
    yAxis: { type: 'value' as const, show: false },
    series: [{
      type: 'bar' as const, data: data.map(d => d.value), barWidth: '52%',
      itemStyle: { borderRadius: [8, 8, 0, 0], color: linearGradient('#69b7ff', '#1677FF') },
      label: { show: true, position: 'top' as const, color: T.steel, fontSize: 12, fontWeight: 600 },
    }],
  }
}

// ═══════════════════════════════════════════════════════════════
// KPI 卡片
// ═══════════════════════════════════════════════════════════════
function KpiCard({ title, value, icon, accent, unit = '人' }: {
  title: string; value: number; icon: ReactNode; accent: string; unit?: string
}) {
  const animatedValue = useCountUp(value, 1400)

  return (
    <div
      className="group relative overflow-hidden animate-fade-in-up"
      style={{
        borderRadius: 16, background: T.canvas,
        border: `1px solid ${T.hairline}`,
        transition: 'all 300ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = `0 8px 30px rgba(0,0,0,0.08), 0 0 0 1px ${accent}30`
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = ''
        e.currentTarget.style.boxShadow = ''
      }}
    >
      {/* 背景装饰圆 */}
      <div className="absolute -right-4 -top-4 rounded-full opacity-[0.06] pointer-events-none" style={{ width: 88, height: 88, background: accent }} />
      <div className="absolute -right-2 -top-2 rounded-full opacity-[0.04] pointer-events-none" style={{ width: 56, height: 56, background: accent }} />

      <div className="relative p-5">
        {/* 图标 */}
        <div className="flex items-center justify-center shrink-0 mb-3"
          style={{
            width: 44, height: 44, borderRadius: 14,
            background: `linear-gradient(135deg, ${accent}20, ${accent}08)`,
            color: accent, fontSize: 22,
            boxShadow: `0 2px 8px ${accent}18`,
          }}>
          {icon}
        </div>

        {/* 数字 */}
        <div className="text-[34px] font-bold leading-none tracking-tight mb-1"
          style={{ color: T.ink, fontFeatureSettings: '"tnum"', letterSpacing: '-0.02em' }}>
          {animatedValue.toLocaleString('zh-CN')}
          <span className="text-[18px] font-medium ml-1" style={{ color: T.steel }}>{unit}</span>
        </div>

        {/* 标题 */}
        <div className="text-[13px] font-medium" style={{ color: T.steel }}>{title}</div>
      </div>
    </div>
  )
}

// 主指标卡：彩色标题 + 超大彩色数字（对齐设计稿「目前在职人数」样式）
function HeroStatCard({ title, value, accent, unit = '人' }: {
  title: string; value: number; accent: string; unit?: string
}) {
  const animatedValue = useCountUp(value, 1400)
  return (
    <div
      className="group relative overflow-hidden animate-fade-in-up"
      style={{
        borderRadius: 16, background: T.canvas, border: `1px solid ${T.hairline}`,
        transition: 'all 300ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = `0 8px 30px rgba(0,0,0,0.08), 0 0 0 1px ${accent}30`
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = ''
        e.currentTarget.style.boxShadow = ''
      }}
    >
      <div className="absolute -right-4 -bottom-8 rounded-full opacity-[0.05] pointer-events-none" style={{ width: 120, height: 120, background: accent }} />
      <div className="relative p-5 h-full flex flex-col justify-between" style={{ minHeight: 128 }}>
        <div className="text-[14px] font-medium" style={{ color: accent }}>{title}</div>
        <div className="text-[44px] font-bold leading-none tracking-tight"
          style={{ color: accent, fontFeatureSettings: '"tnum"', letterSpacing: '-0.02em' }}>
          {animatedValue.toLocaleString('zh-CN')}
          <span className="text-[18px] font-medium ml-1" style={{ color: T.steel }}>{unit}</span>
        </div>
      </div>
    </div>
  )
}

// 双指标卡：一张卡内两个并排大数字（对齐设计稿「今日入职/离职」「本月入职/离职」）
function DualStat({ label, value }: { label: string; value: number }) {
  const animatedValue = useCountUp(value, 1400)
  return (
    <div className="text-center">
      <div className="text-[36px] font-bold leading-none tracking-tight mb-1.5"
        style={{ color: T.primary, fontFeatureSettings: '"tnum"', letterSpacing: '-0.02em' }}>
        {animatedValue.toLocaleString('zh-CN')}
      </div>
      <div className="text-[13px] font-medium" style={{ color: T.steel }}>{label}</div>
    </div>
  )
}

function DualStatCard({ items }: { items: { label: string; value: number }[] }) {
  return (
    <div
      className="animate-fade-in-up"
      style={{
        borderRadius: 16, background: T.canvas, border: `1px solid ${T.hairline}`,
        transition: 'all 300ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 8px 30px rgba(0,0,0,0.08)' }}
      onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '' }}
    >
      <div className="p-5 h-full grid grid-cols-2 gap-3 items-center" style={{ minHeight: 128 }}>
        {items.map(it => <DualStat key={it.label} label={it.label} value={it.value} />)}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 倒计时（目标日期可配置，持久化到 localStorage）
// ═══════════════════════════════════════════════════════════════
const LS_COUNTDOWN_TARGET = 'hr_db_countdown_target'

function CountdownCard() {
  const [now, setNow] = useState(() => new Date())
  const [target, setTarget] = useState<Dayjs>(() => {
    const saved = loadLS<string | null>(LS_COUNTDOWN_TARGET, null)
    return saved ? dayjs(saved) : dayjs('2026-12-31')
  })
  const [pickerOpen, setPickerOpen] = useState(false)
  const [tempDate, setTempDate] = useState<Dayjs | null>(null)

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000) // 秒级刷新：天/时/分/秒方块
    return () => clearInterval(t)
  }, [])

  const targetDate = useMemo(() => target.endOf('day').toDate(), [target])
  const yearStart = useMemo(() => target.startOf('year').toDate(), [target])
  const diffMs = targetDate.getTime() - now.getTime()
  const isOver = diffMs <= 0
  const daysLeft = Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)))
  const hoursLeft = Math.max(0, Math.floor(diffMs / (1000 * 60 * 60)) % 24)
  const minutesLeft = Math.max(0, Math.floor(diffMs / (1000 * 60)) % 60)
  const secondsLeft = Math.max(0, Math.floor(diffMs / 1000) % 60)
  const totalMs = targetDate.getTime() - yearStart.getTime()
  const elapsedMs = now.getTime() - yearStart.getTime()
  const progress = Math.min(100, Math.max(0, Math.round((elapsedMs / totalMs) * 100)))
  const label = target.format('YYYY年M月D日')
  // 目标为年末时标题对齐设计稿「XXXX 年结束」
  const isYearEnd = target.month() === 11 && target.date() === 31
  const title = isYearEnd ? `${target.year()} 年结束` : `距 ${label}`

  const openPicker = () => { setTempDate(target); setPickerOpen(true) }
  const confirmDate = () => {
    if (tempDate) {
      setTarget(tempDate)
      saveLS(LS_COUNTDOWN_TARGET, tempDate.format('YYYY-MM-DD'))
    }
    setPickerOpen(false)
  }

  const blocks = [
    { v: daysLeft, u: '天' }, { v: hoursLeft, u: '时' },
    { v: minutesLeft, u: '分' }, { v: secondsLeft, u: '秒' },
  ]

  return (
    <>
    <div
      className="group relative overflow-hidden animate-fade-in-up cursor-pointer"
      style={{
        borderRadius: 16, background: T.canvas, border: `1px solid ${T.hairline}`,
        transition: 'all 300ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 8px 30px rgba(0,0,0,0.08)' }}
      onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '' }}
      onClick={openPicker}
    >
      <div className="relative p-5 h-full flex flex-col justify-between" style={{ minHeight: 128 }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center shrink-0"
              style={{ width: 30, height: 30, borderRadius: 9, background: `${T.primary}18`, color: T.primary, fontSize: 15 }}>
              <ClockCircleOutlined />
            </div>
            <span className="text-[14px] font-semibold" style={{ color: T.charcoal }}>{title}</span>
          </div>
          <div className="flex items-center gap-1 px-2 py-1 rounded-lg"
            style={{ background: T.surface, color: T.steel, fontSize: 11 }}
            onClick={e => { e.stopPropagation(); setPickerOpen(true) }}>
            <EditOutlined />
          </div>
        </div>

        {isOver ? (
          <div className="text-[36px] font-bold leading-none" style={{ color: T.success }}>🎉</div>
        ) : (
          <div className="flex items-center justify-between gap-1">
            {blocks.map((b, i) => (
              <div key={b.u} className="flex items-center gap-1">
                <div className="flex flex-col items-center rounded-xl"
                  style={{ background: T.primary, minWidth: 48, padding: '8px 6px 6px' }}>
                  <span className="text-[22px] font-bold leading-none" style={{ color: '#fff', fontFeatureSettings: '"tnum"' }}>
                    {String(b.v).padStart(2, '0')}
                  </span>
                  <span className="text-[11px] mt-1" style={{ color: 'rgba(255,255,255,0.75)' }}>{b.u}</span>
                </div>
                {i < blocks.length - 1 && <span style={{ color: T.muted, fontSize: 13, fontWeight: 600 }}>:</span>}
              </div>
            ))}
          </div>
        )}

        {!isOver && (
          <div className="rounded-full overflow-hidden" style={{ height: 4, background: T.surface }}>
            <div className="h-full rounded-full transition-all duration-1000" style={{ width: `${progress}%`, background: T.primary }} />
          </div>
        )}
      </div>
    </div>

    <Modal
      title="设置倒计时目标日期"
      open={pickerOpen}
      onOk={confirmDate}
      onCancel={() => setPickerOpen(false)}
      okText="确定"
      cancelText="取消"
      width={320}
    >
      <div className="flex justify-center py-4">
        <DatePicker
          value={tempDate}
          onChange={d => setTempDate(d)}
          needConfirm={false}
          style={{ width: '100%' }}
        />
      </div>
    </Modal>
    </>
  )
}

// ═══════════════════════════════════════════════════════════════
// 骨架屏
// ═══════════════════════════════════════════════════════════════
function DashboardSkeleton() {
  return (
    <div className="space-y-6 pb-6 animate-fade-in-up">
      <div className="flex justify-between items-center">
        <Skeleton.Input active size="large" style={{ width: 180, height: 32 }} />
        <Skeleton.Button active size="large" />
      </div>
      <Row gutter={[16, 16]}>
        {[0, 1, 2].map(i => (
          <Col key={i} xs={24} sm={8}>
            <div className="rounded-2xl border p-5" style={{ borderColor: T.hairline, background: T.canvas }}>
              <Skeleton.Avatar active size={44} shape="square" style={{ borderRadius: 14, marginBottom: 12 }} />
              <Skeleton.Input active style={{ width: 100, height: 36, marginBottom: 8 }} />
              <Skeleton.Input active size="small" style={{ width: 80 }} />
            </div>
          </Col>
        ))}
      </Row>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} className="md:col-span-2">
            <div className="rounded-2xl border p-5" style={{ borderColor: T.hairline, background: T.canvas }}>
              <div className="flex items-center gap-2 mb-4">
                <Skeleton.Avatar active size={14} shape="circle" />
                <Skeleton.Input active size="small" style={{ width: 140 }} />
              </div>
              <div className="animate-pulse rounded-xl" style={{ height: 300, background: T.surface }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════════
export default function DashboardClient() {
  const { message } = App.useApp()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [addModalOpen, setAddModalOpen] = useState(false)

  const [chartOrder, setChartOrder] = useState<string[]>(() => loadLS(LS_ORDER, [...PRESET_IDS]))
  const [chartTypes, setChartTypes] = useState<Record<string, ChartType>>(() =>
    loadLS(LS_TYPES, Object.fromEntries(ALL_STAT_TYPES.map(s => [s.id, s.defaultType]))))
  const [chartHeights, setChartHeights] = useState<Record<string, number>>(() =>
    loadLS(LS_HEIGHTS, Object.fromEntries(ALL_STAT_TYPES.map(s => [s.id, DEFAULT_H]))))
  const [chartWidths, setChartWidths] = useState<Record<string, number>>(() =>
    loadLS(LS_WIDTHS, Object.fromEntries(ALL_STAT_TYPES.map(s => [s.id, DEFAULT_PRESET_WIDTHS[s.id] ?? 12]))))

  const [moreKpiOpen, setMoreKpiOpen] = useState(false)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)

  const resizeState = useRef<{ id: string; sx: number; sy: number; sw: number; sh: number; snapped: boolean } | null>(null)
  const resizeRaf = useRef<number>(0)

  // ── 数据获取 ──
  useEffect(() => {
    fetchDashboardStats().then(setStats).catch(err => message.error(err.message || '加载失败')).finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── 持久化 ──
  useEffect(() => { saveLS(LS_ORDER, chartOrder) }, [chartOrder])
  useEffect(() => { saveLS(LS_TYPES, chartTypes) }, [chartTypes])
  useEffect(() => { saveLS(LS_HEIGHTS, chartHeights) }, [chartHeights])
  useEffect(() => { saveLS(LS_WIDTHS, chartWidths) }, [chartWidths])

  // ── 缩放监听（宽度沿 4 档位步进，高度连续）──
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!resizeState.current) return
      const rs = resizeState.current; const dx = e.clientX - rs.sx; const dy = e.clientY - rs.sy
      let newW = rs.sw
      if (!rs.snapped && Math.abs(dx) >= SNAP_X) {
        const tierIdx = WIDTH_TIERS.indexOf(rs.sw as (typeof WIDTH_TIERS)[number])
        if (tierIdx >= 0) {
          const nextIdx = Math.min(WIDTH_TIERS.length - 1, Math.max(0, tierIdx + (dx > 0 ? 1 : -1)))
          newW = WIDTH_TIERS[nextIdx]
          if (newW !== rs.sw) { rs.sw = newW; rs.sx = e.clientX; rs.snapped = true }
        }
      }
      if (rs.snapped && Math.abs(dx) < SNAP_X * 0.3) rs.snapped = false
      const newH = Math.min(MAX_H, Math.max(MIN_H, rs.sh + dy))
      if (resizeRaf.current) cancelAnimationFrame(resizeRaf.current)
      resizeRaf.current = requestAnimationFrame(() => {
        setChartWidths(prev => ({ ...prev, [rs.id]: newW }))
        setChartHeights(prev => ({ ...prev, [rs.id]: newH }))
      })
    }
    const onUp = () => {
      if (resizeRaf.current) cancelAnimationFrame(resizeRaf.current)
      if (resizeState.current) { document.body.style.cursor = ''; document.body.style.userSelect = '' }
      resizeState.current = null
    }
    window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  }, [])

  const startResize = useCallback((chartId: string, e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation()
    document.body.style.cursor = 'nwse-resize'; document.body.style.userSelect = 'none'
    resizeState.current = { id: chartId, sx: e.clientX, sy: e.clientY, sw: chartWidths[chartId] || 12, sh: chartHeights[chartId] || DEFAULT_H, snapped: false }
  }, [chartWidths, chartHeights])

  // ── 拖拽 ──
  const onDragStart = useCallback((idx: number) => setDragIndex(idx), [])
  const onDragOver = useCallback((e: React.DragEvent, idx: number) => { e.preventDefault(); setDragOverIndex(idx) }, [])
  const onDrop = useCallback((e: React.DragEvent, dropIdx: number) => {
    e.preventDefault(); if (dragIndex === null || dragIndex === dropIdx) return
    setChartOrder(prev => { const n = [...prev]; const [m] = n.splice(dragIndex, 1); n.splice(dropIdx, 0, m); return n })
    setDragIndex(null); setDragOverIndex(null)
  }, [dragIndex])
  const onDragEnd = useCallback(() => { setDragIndex(null); setDragOverIndex(null) }, [])

  // ── 卡片管理 ──
  const addChart = useCallback((typeId: string) => {
    if (chartOrder.includes(typeId)) return
    setChartOrder(prev => [...prev, typeId]); setChartHeights(prev => ({ ...prev, [typeId]: DEFAULT_H })); setChartWidths(prev => ({ ...prev, [typeId]: DEFAULT_PRESET_WIDTHS[typeId] ?? 12 }))
    setAddModalOpen(false)
  }, [chartOrder])
  const removeChart = useCallback((id: string) => { if (!PRESET_IDS.includes(id)) setChartOrder(prev => prev.filter(x => x !== id)) }, [])

  // ── 数据映射 ──
  const getChartData = useCallback((chartId: string) => {
    if (!stats) return null
    switch (chartId) {
      case 'education': return stats.education_distribution
      case 'department': return stats.department_distribution
      case 'dept-ranking': return stats.department_distribution
      case 'hires-by-dept': return stats.monthly_hires_by_dept
      case 'hires-by-dept-year': return stats.hires_by_dept_year
      case 'hire-departure-trend': {
        // 入离职两序列都有数据即视为可用
        const hasAny = stats.monthly_hires.length > 0 || stats.monthly_departures.length > 0
        return hasAny ? [...stats.monthly_hires, ...stats.monthly_departures] : null
      }
      case 'monthly-hires': return stats.monthly_hires
      case 'monthly-hires-by-category': return stats.monthly_hires_by_category
      case 'monthly-departures': return stats.monthly_departures
      case 'monthly-departures-by-category': return stats.monthly_departures_by_category
      case 'departure-comparison': return stats.monthly_departure_comparison
      case 'departures-by-dept': return stats.departures_by_dept
      case 'position-departure-top': return stats.position_departure_top
      case 'monthly-departure-rate': return stats.monthly_departure_rate
      case 'contract-expiry': return stats.contract_expiry
      default: {
        const dsKey = STAT_TYPE_MAP[chartId]?.dataSource
        return dsKey && stats.distributions ? (stats.distributions as Record<string, DistributionItem[]>)[dsKey] || null : null
      }
    }
  }, [stats])

  // ── ECharts 选项 ──
  const chartOptions = useMemo(() => {
    if (!stats) return {} as Record<string, EChartsOption>
    const opts: Record<string, EChartsOption> = {}
    chartOrder.forEach(chartId => {
      const type = chartTypes[chartId] || STAT_TYPE_MAP[chartId]?.defaultType || 'pie'
      const data = getChartData(chartId)
      if (!data || data.length === 0) { opts[chartId] = {}; return }
      if (chartId === 'hires-by-dept') { opts[chartId] = buildGroupedBarOption(data as MonthlyByDeptItem[], 'department') }
      else if (chartId === 'monthly-hires-by-category') { opts[chartId] = buildGroupedBarOption(data as MonthlyByCategoryItem[], 'category') }
      else if (chartId === 'monthly-departures-by-category') { opts[chartId] = buildGroupedBarOption(data as MonthlyByCategoryItem[], 'category') }
      else if (chartId === 'hire-departure-trend') { opts[chartId] = buildHireDepartureLineOption(stats.monthly_hires, stats.monthly_departures) }
      else if (chartId === 'departure-comparison') { opts[chartId] = buildComparisonOption(data as MonthlyComparisonItem[]) }
      else if (chartId === 'dept-ranking') { opts[chartId] = buildHorizontalBarOption(data as DistributionItem[], 10) }
      else if (chartId === 'departures-by-dept') { opts[chartId] = buildHorizontalBarOption(data as DistributionItem[]) }
      else if (chartId === 'gender') {
        opts[chartId] = buildPieOption(data as DistributionItem[], { '男': T.primary, '女': T.success })
      }
      else if (chartId === 'age-overview') { opts[chartId] = buildAgeOverviewOption(data as DistributionItem[]) }
      else if (type === 'pie') { opts[chartId] = buildPieOption(data as DistributionItem[]) }
      else if (chartId === 'monthly-departures') { const d = data as MonthlyItem[]; opts[chartId] = buildBarOption(d.map(r => r.month), d.map(r => r.value), PALETTE[8]) }
      else if (chartId === 'monthly-departure-rate') { const d = data as MonthlyItem[]; opts[chartId] = buildBarOption(d.map(r => r.month), d.map(r => r.value), PALETTE[8]) }
      else if (chartId === 'monthly-hires') { const d = data as MonthlyItem[]; opts[chartId] = buildBarOption(d.map(r => r.month), d.map(r => r.value), PALETTE[3]) }
      else { opts[chartId] = buildDistributionBarOption(data as DistributionItem[]) }
    })
    return opts
  }, [stats, chartOrder, chartTypes, getChartData])

  // ═══ 渲染 ═══
  if (loading) return <DashboardSkeleton />
  if (!stats) return <div className="flex flex-col items-center justify-center py-20"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" /></div>

  const { summary } = stats
  const availableTypes = ALL_STAT_TYPES.filter(t => !chartOrder.includes(t.id))

  return (
    <div className="space-y-6 p-5 pb-8 animate-fade-in-up" style={{ background: T.pageBg, borderRadius: 16 }}>
      {/* 标题栏 */}
      <div className="flex justify-between items-center animate-fade-in-up">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight" style={{ color: T.ink }}>人事数据看板</h1>
          <p className="text-sm mt-0.5" style={{ color: T.steel }}>员工结构 · 入职离职 · 多维分析</p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)} disabled={availableTypes.length === 0} size="large" style={{ borderRadius: 10, background: T.primary }}>
          添加卡片
        </Button>
      </div>

      {/* KPI 首行：对齐设计稿（倒计时 · 在职 · 今日入/离职 · 本月入/离职） */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <CountdownCard />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <HeroStatCard title="目前在职人数" value={summary.total_employees} accent={T.success} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <DualStatCard items={[
            { label: '今日入职人数', value: summary.today_hires ?? 0 },
            { label: '今日离职人数', value: summary.today_departures ?? 0 },
          ]} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <DualStatCard items={[
            { label: '本月入职人数', value: summary.new_hires_this_month },
            { label: '本月离职总数', value: summary.departures_this_month },
          ]} />
        </Col>
      </Row>

      {/* 更多指标（默认收起） */}
      <div>
        <Button
          type="text" size="small"
          icon={<DownOutlined style={{ fontSize: 11, transition: 'transform 200ms', transform: moreKpiOpen ? 'rotate(180deg)' : '' }} />}
          onClick={() => setMoreKpiOpen(v => !v)}
          style={{ color: T.slate, padding: '2px 8px', marginBottom: moreKpiOpen ? 12 : 0 }}
        >
          更多指标（试用期 · 司龄 · 编制 · 风险 · 绩效）
        </Button>
        {moreKpiOpen && (
          <Row gutter={[16, 16]}>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="试用期人数" value={summary.probation_count ?? 0} icon={<SafetyCertificateOutlined />} accent={T.primary} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="平均司龄" value={summary.avg_tenure ?? 0} icon={<FieldTimeOutlined />} accent={T.blue} unit="年" />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="本月净增人数" value={summary.net_growth_this_month ?? 0} icon={<RiseOutlined />} accent={T.success} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="90天内合同到期" value={summary.contract_expiry_90 ?? 0} icon={<AlertOutlined />} accent={T.error} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title={`编制数（达成率 ${summary.quota_rate ?? 0}%）`} value={summary.quota_total ?? 0} icon={<ApartmentOutlined />} accent={T.primary} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="本年工伤人次" value={summary.work_injury_count ?? 0} icon={<AlertOutlined />} accent={T.error} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="本年劳动纠纷" value={summary.labor_dispute_count ?? 0} icon={<ExclamationCircleOutlined />} accent={T.error} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="本年被动离职" value={summary.passive_departures ?? 0} icon={<UserDeleteOutlined />} accent={T.error} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="绩效不合格部门数" value={summary.underperforming_count ?? 0} icon={<WarningOutlined />} accent={T.error} />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="已完成绩效评估" value={summary.performance_submitted_count ?? 0} icon={<CheckCircleOutlined />} accent={T.success} unit="份" />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="主动离职率" value={summary.active_departure_rate ?? 0} icon={<UserDeleteOutlined />} accent={T.error} unit="%" />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <KpiCard title="被动离职率" value={summary.passive_departure_rate ?? 0} icon={<UserDeleteOutlined />} accent={T.error} unit="%" />
            </Col>
          </Row>
        )}
      </div>

      {/* 图表网格（12 列，支持 1/3、1/2、2/3、全宽四档） */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
        {chartOrder.map((chartId, idx) => {
          const config = STAT_TYPE_MAP[chartId]; if (!config) return null
          const isPreset = PRESET_IDS.includes(chartId)
          const cols = chartWidths[chartId] || DEFAULT_PRESET_WIDTHS[chartId] || 12; const height = chartHeights[chartId] || DEFAULT_H
          const isDragging = dragIndex === idx; const isOver = dragOverIndex === idx && dragIndex !== idx
          const data = getChartData(chartId); const option = chartOptions[chartId]

          return (
            <div key={chartId} draggable
              onDragStart={() => onDragStart(idx)} onDragOver={e => onDragOver(e, idx)}
              onDrop={e => onDrop(e, idx)} onDragEnd={onDragEnd}
              className={`${SPAN_CLASS[cols] || SPAN_CLASS[12]} animate-fade-in-up`}
              style={{
                animationDelay: `${idx * 80}ms`,
                transition: 'all 300ms cubic-bezier(0.16, 1, 0.3, 1)',
                ...(isDragging ? { opacity: 0.35, transform: 'scale(0.96)' } : {}),
              }}
            >
              <div style={{ position: 'relative' }}>
                {/* 拖拽指示线 */}
                {isOver && <div className="absolute -top-1 left-0 right-0 z-10 rounded-full" style={{ height: 3, background: T.primary }} />}

                <Card variant="borderless"
                  className="transition-all duration-300"
                  onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 4px 20px rgba(15,15,15,0.07)'; e.currentTarget.style.borderColor = T.hairlineStrong }}
                  onMouseLeave={e => { e.currentTarget.style.boxShadow = ''; e.currentTarget.style.borderColor = '' }}
                  title={
                    <div className="flex items-center gap-2 select-none" style={{ cursor: dragIndex !== null ? 'grabbing' : 'grab' }}>
                      <HolderOutlined className="transition-colors duration-200" style={{ color: dragIndex === idx ? T.primary : T.muted, fontSize: 14 }} />
                      <span className="text-[15px] font-semibold" style={{ color: T.charcoal }}>{config.title}</span>
                      <span style={{ fontSize: 11, color: T.steel, fontWeight: 400, background: T.surface, borderRadius: 999, padding: '1px 8px' }}>
                        {WIDTH_LABELS[cols] || '全宽'}
                      </span>
                    </div>
                  }
                  extra={
                    <div className="flex items-center gap-2">
                      {!CUSTOM_RENDER_IDS.includes(chartId) && (
                      <Segmented size="small" value={chartTypes[chartId] || config.defaultType}
                        onChange={v => setChartTypes(prev => ({ ...prev, [chartId]: v as ChartType }))}
                        options={[
                          { label: <><PieChartOutlined style={{ marginRight: 4 }} />饼图</>, value: 'pie' },
                          { label: <><BarChartOutlined style={{ marginRight: 4 }} />柱状图</>, value: 'bar' },
                        ]} />
                      )}
                      {!isPreset && (
                        <Button type="text" size="small" icon={<CloseOutlined />} aria-label="删除卡片"
                          onClick={e => { e.stopPropagation(); removeChart(chartId) }} style={{ color: T.steel }} />
                      )}
                    </div>
                  }
                  style={{ borderRadius: 16, border: isOver ? `2px solid ${T.primary}` : `1px solid ${T.hairline}`, transition: 'border-color 200ms, box-shadow 300ms' }}
                >
                  {!data || data.length === 0 ? (
                    <div className="flex flex-col items-center justify-center gap-2" style={{ height }}>
                      <div className="text-4xl opacity-20">📊</div>
                      <span style={{ color: T.muted, fontSize: 14 }}>暂无数据</span>
                    </div>
                  ) : chartId === 'age-overview' && stats ? (
                    <div className="flex flex-col" style={{ height }}>
                      {/* 对齐设计稿：顶部青色大字平均年龄 + 下方年龄分布简洁柱 */}
                      <div className="flex items-baseline gap-2 pb-1">
                        <span className="text-[14px] font-medium" style={{ color: T.steel }}>平均年龄</span>
                        <span className="text-[40px] font-bold leading-none tracking-tight" style={{ color: '#13c2c2', fontFeatureSettings: '"tnum"' }}>
                          {stats.summary.age_avg}
                        </span>
                        <span className="text-[14px]" style={{ color: T.steel }}>岁</span>
                      </div>
                      <ReactECharts option={option} style={{ height: Math.max(MIN_H - 56, height - 56), width: '100%' }} notMerge lazyUpdate />
                    </div>
                  ) : (
                    <ReactECharts option={option} style={{ height, width: '100%' }} notMerge lazyUpdate />
                  )}
                </Card>

                {/* 缩放手柄 */}
                <div onMouseDown={e => startResize(chartId, e)} title="拖拽缩放卡片大小"
                  className="group/resize"
                  style={{ position: 'absolute', bottom: 0, right: 0, width: 28, height: 28, cursor: 'nwse-resize', display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-end', padding: 5, zIndex: 5 }}>
                  <svg width="12" height="12" viewBox="0 0 12 12" className="opacity-30 group-hover/resize:opacity-60 transition-opacity">
                    <path d="M0 12L12 0V2L2 12H0Z" fill={T.muted} />
                    <path d="M4 12L12 4V6L6 12H4Z" fill={T.muted} />
                    <path d="M8 12L12 8V10L10 12H8Z" fill={T.muted} />
                  </svg>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* 空图表提示 */}
      {chartOrder.length === 0 && (
        <div className="text-center py-12 animate-fade-in-up" style={{ color: T.muted }}>暂无图表卡片，点击「添加卡片」开始</div>
      )}

      {/* 添加卡片 Modal */}
      <Modal title="选择统计类型" open={addModalOpen} onCancel={() => setAddModalOpen(false)} footer={null} width={640}>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {availableTypes.map(t => {
            const isPie = t.defaultType === 'pie'; const accent = isPie ? PALETTE[5] : T.blue
            return (
              <Card key={t.id} hoverable size="small" onClick={() => addChart(t.id)}
                className="transition-all duration-200 hover:-translate-y-0.5" style={{ borderRadius: 12, textAlign: 'center', cursor: 'pointer' }}>
                <div className="flex justify-center mb-2">
                  <div className="flex items-center justify-center"
                    style={{ width: 40, height: 40, borderRadius: 10, background: `linear-gradient(135deg, ${accent}18, ${accent}08)`, color: accent, fontSize: 18 }}>
                    {isPie ? <PieChartOutlined /> : <BarChartOutlined />}
                  </div>
                </div>
                <div className="font-medium text-sm" style={{ color: T.charcoal }}>{t.title}</div>
                <div className="text-xs" style={{ color: T.muted }}>{t.group}</div>
              </Card>
            )
          })}
        </div>
        {availableTypes.length === 0 && <div className="text-center py-8" style={{ color: T.muted }}>所有统计类型已添加</div>}
      </Modal>
    </div>
  )
}

// ── 动画注入（仅浏览器端执行一次）──
if (typeof document !== 'undefined') {
  const STYLE_ID = 'hr-dashboard-anim'
  if (!document.getElementById(STYLE_ID)) {
    const s = document.createElement('style')
    s.id = STYLE_ID
    s.textContent = `
      @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(16px); }
        to   { opacity: 1; transform: translateY(0); }
      }
      .animate-fade-in-up {
        animation: fadeInUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
      }
    `
    document.head.appendChild(s)
  }
}
