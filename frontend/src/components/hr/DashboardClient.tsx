'use client'

import { useState, useEffect, useCallback, useRef, useMemo, type ReactNode } from 'react'
import { App, Card, Row, Col, Segmented, Button, Modal, Empty, Skeleton, DatePicker } from 'antd'
import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import {
  TeamOutlined, UserAddOutlined, UserDeleteOutlined,
  HolderOutlined, PlusOutlined, CloseOutlined,
  PieChartOutlined, BarChartOutlined, ClockCircleOutlined, EditOutlined,
} from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchDashboardStats } from '@/actions/hr'
import type { DashboardStats, DistributionItem, MonthlyByDeptItem, MonthlyItem, MonthlyComparisonItem } from '@/types/hr'

type ChartType = 'pie' | 'bar'

// ═══════════════════════════════════════════════════════════════
// 设计令牌
// ═══════════════════════════════════════════════════════════════
const T = {
  primary: '#5645d4',
  canvas: '#ffffff',
  surface: '#f6f5f4',
  ink: '#1a1a1a',
  charcoal: '#37352f',
  slate: '#5d5b54',
  steel: '#787671',
  stone: '#a4a097',
  muted: '#bbb8b1',
  hairline: '#e5e3df',
  hairlineStrong: '#c8c4be',
  hairlineSoft: '#ede9e4',
  success: '#1aae39',
  error: '#e03131',
  blue: '#0075de',
} as const

const PALETTE = ['#5645d4', '#0075de', '#1aae39', '#dd5b00', '#7b3ff2', '#2a9d99', '#e8b830', '#e03131', '#ff64c8', '#0a1530']

const DEFAULT_H = 350; const MIN_H = 200; const MAX_H = 900; const SNAP_X = 80
const PRESET_IDS = ['education', 'department', 'hires-by-dept', 'monthly-departures', 'departure-comparison']

interface StatTypeOption { id: string; title: string; defaultType: ChartType; group: string; dataSource: string }

const ALL_STAT_TYPES: StatTypeOption[] = [
  { id: 'education', title: '学历分布', defaultType: 'pie', group: '人员结构', dataSource: 'preset' },
  { id: 'department', title: '部门人数分布', defaultType: 'pie', group: '人员结构', dataSource: 'preset' },
  { id: 'dept-ranking', title: '部门人数排行', defaultType: 'bar', group: '人员结构', dataSource: 'preset' },
  { id: 'hires-by-dept', title: '入职各部门月度统计', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'monthly-hires', title: '每月入职人数', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'monthly-departures', title: '离职月度统计', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'departure-comparison', title: '离职月度对比', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'departures-by-dept', title: '2026年离职各部门', defaultType: 'bar', group: '入职/离职', dataSource: 'preset' },
  { id: 'gender', title: '性别分布', defaultType: 'pie', group: '人员结构', dataSource: 'gender' },
  { id: 'age', title: '年龄区间分布', defaultType: 'bar', group: '人员结构', dataSource: 'age' },
  { id: 'level', title: '职级分布', defaultType: 'pie', group: '人员结构', dataSource: 'level' },
  { id: 'position', title: '岗位分布', defaultType: 'bar', group: '人员结构', dataSource: 'position' },
  { id: 'job_category', title: '职类分布', defaultType: 'pie', group: '人员结构', dataSource: 'job_category' },
  { id: 'political_status', title: '政治面貌分布', defaultType: 'pie', group: '人员结构', dataSource: 'political_status' },
  { id: 'contract_type', title: '合同类型分布', defaultType: 'pie', group: '人员结构', dataSource: 'contract_type' },
  { id: 'tenure', title: '司龄分布', defaultType: 'bar', group: '人员结构', dataSource: 'tenure' },
]

const STAT_TYPE_MAP: Record<string, StatTypeOption> = Object.fromEntries(ALL_STAT_TYPES.map(s => [s.id, s]))

const LS_ORDER = 'hr_db_v3_order'; const LS_TYPES = 'hr_db_v3_types'
const LS_HEIGHTS = 'hr_db_v3_heights'; const LS_WIDTHS = 'hr_db_v3_widths'

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

function buildPieOption(data: DistributionItem[]): EChartsOption {
  return {
    color: PALETTE,
    animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'item' as const, formatter: '<b>{b}</b><br/>人数: {c} 人 ({d}%)' },
    legend: { bottom: 0, textStyle: { ...ECHART_TEXT_STYLE, fontSize: 11 }, itemWidth: 10, itemHeight: 10, itemGap: 12 },
    series: [{
      type: 'pie' as const, radius: ['52%', '80%'], center: ['50%', '44%'], avoidLabelOverlap: false,
      itemStyle: { borderColor: T.canvas, borderWidth: 2 },
      data: data.map(d => ({ name: d.name, value: d.value })),
      label: { show: false },
      emphasis: {
        // 高亮标签放圆环中心，避免 outside 标签在顶部被画布裁掉一半
        label: {
          show: true, position: 'center' as const,
          formatter: '{b}\n{c} 人（{d}%）',
          fontSize: 14, fontWeight: 'bold' as const, color: T.charcoal, lineHeight: 24,
        },
        scaleSize: 8,
      },
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

function buildGroupedBarOption(data: MonthlyByDeptItem[]): EChartsOption {
  const months = [...new Set(data.map(d => d.month))].sort()
  const departments = [...new Set(data.map(d => d.department))]
  return {
    color: PALETTE, animationDuration: 800, animationEasing: 'cubicOut' as const,
    tooltip: { ...BASE_TOOLTIP, trigger: 'axis' as const },
    grid: { left: 48, right: 20, top: 20, bottom: 48 },
    legend: { bottom: 0, textStyle: { ...ECHART_TEXT_STYLE, fontSize: 11 }, itemWidth: 10, itemHeight: 10, itemGap: 12 },
    xAxis: {
      type: 'category' as const, data: months,
      axisLabel: { ...ECHART_AXIS_LABEL, rotate: months.length > 6 ? 35 : 0 },
      axisTick: { show: false }, axisLine: { lineStyle: { color: T.hairline } },
    },
    yAxis: {
      type: 'value' as const, axisLabel: ECHART_AXIS_LABEL,
      splitLine: ECHART_SPLIT_LINE, axisLine: { show: false }, axisTick: { show: false },
    },
    series: departments.map(dept => ({
      name: dept, type: 'bar' as const, barGap: '30%' as const,
      data: months.map(m => data.find(d => d.month === m && d.department === dept)?.value || 0),
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

function buildHorizontalBarOption(data: DistributionItem[]): EChartsOption {
  const sorted = [...data].sort((a, b) => a.value - b.value) // 小→大，底部→顶部
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

// ═══════════════════════════════════════════════════════════════
// KPI 卡片
// ═══════════════════════════════════════════════════════════════
function KpiCard({ title, value, icon, accent }: {
  title: string; value: number; icon: ReactNode; accent: string
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
          <span className="text-[18px] font-medium ml-1" style={{ color: T.steel }}>人</span>
        </div>

        {/* 标题 */}
        <div className="text-[13px] font-medium" style={{ color: T.steel }}>{title}</div>
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
    const t = setInterval(() => setNow(new Date()), 1000 * 60)
    return () => clearInterval(t)
  }, [])

  const targetDate = useMemo(() => target.endOf('day').toDate(), [target])
  const yearStart = useMemo(() => target.startOf('year').toDate(), [target])
  const diffMs = targetDate.getTime() - now.getTime()
  const daysLeft = Math.max(0, Math.ceil(diffMs / (1000 * 60 * 60 * 24)))
  const totalMs = targetDate.getTime() - yearStart.getTime()
  const elapsedMs = now.getTime() - yearStart.getTime()
  const progress = Math.min(100, Math.max(0, Math.round((elapsedMs / totalMs) * 100)))
  const label = target.format('YYYY年M月D日')
  const isOver = daysLeft === 0

  const openPicker = () => { setTempDate(target); setPickerOpen(true) }
  const confirmDate = () => {
    if (tempDate) {
      setTarget(tempDate)
      saveLS(LS_COUNTDOWN_TARGET, tempDate.format('YYYY-MM-DD'))
    }
    setPickerOpen(false)
  }

  return (
    <>
    <div
      className="group relative overflow-hidden animate-fade-in-up cursor-pointer"
      style={{
        borderRadius: 16, background: isOver ? `linear-gradient(135deg, ${T.error}, ${T.error}dd)` : `linear-gradient(135deg, ${T.primary}, ${T.primary}dd)`,
        transition: 'all 300ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = isOver ? '0 8px 30px rgba(224,49,49,0.3)' : '0 8px 30px rgba(86,69,212,0.3)' }}
      onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '' }}
      onClick={openPicker}
    >
      <div className="relative p-5">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center justify-center shrink-0"
            style={{ width: 44, height: 44, borderRadius: 14, background: 'rgba(255,255,255,0.2)', color: '#fff', fontSize: 22 }}>
            <ClockCircleOutlined />
          </div>
          <div className="flex items-center gap-1 px-2 py-1 rounded-lg cursor-pointer"
            style={{ background: 'rgba(255,255,255,0.15)', color: 'rgba(255,255,255,0.8)', fontSize: 11 }}
            onClick={e => { e.stopPropagation(); setPickerOpen(true) }}>
            <EditOutlined />
          </div>
        </div>
        <div className="text-[34px] font-bold leading-none tracking-tight mb-1" style={{ color: '#fff', fontFeatureSettings: '"tnum"', letterSpacing: '-0.02em' }}>
          {isOver ? '🎉' : daysLeft.toLocaleString('zh-CN')}
          {!isOver && <span className="text-[18px] font-medium ml-1" style={{ color: 'rgba(255,255,255,0.7)' }}>天</span>}
        </div>
        <div className="text-[13px] font-medium" style={{ color: 'rgba(255,255,255,0.7)' }}>
          {isOver ? `已到 ${label}` : `距 ${label}`}
        </div>
        {!isOver && (
          <>
            <div className="mt-3 rounded-full overflow-hidden" style={{ height: 4, background: 'rgba(255,255,255,0.2)' }}>
              <div className="h-full rounded-full transition-all duration-1000" style={{ width: `${progress}%`, background: 'rgba(255,255,255,0.9)' }} />
            </div>
            <div className="flex justify-between mt-1.5 text-[11px]" style={{ color: 'rgba(255,255,255,0.5)' }}>
              <span>已过{progress}%</span>
              <span>{target.format('YYYY')}</span>
            </div>
          </>
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
    loadLS(LS_WIDTHS, Object.fromEntries(ALL_STAT_TYPES.map(s => [s.id, 2]))))

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

  // ── 缩放监听 ──
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!resizeState.current) return
      const rs = resizeState.current; const dx = e.clientX - rs.sx; const dy = e.clientY - rs.sy
      let newW = rs.sw
      if (!rs.snapped && Math.abs(dx) >= SNAP_X) { newW = dx > 0 ? 2 : 1; if (newW !== rs.sw) { rs.sw = newW; rs.sx = e.clientX; rs.snapped = true } }
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
    resizeState.current = { id: chartId, sx: e.clientX, sy: e.clientY, sw: chartWidths[chartId] || 2, sh: chartHeights[chartId] || DEFAULT_H, snapped: false }
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
    setChartOrder(prev => [...prev, typeId]); setChartHeights(prev => ({ ...prev, [typeId]: DEFAULT_H })); setChartWidths(prev => ({ ...prev, [typeId]: 2 }))
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
      case 'monthly-hires': return stats.monthly_hires
      case 'monthly-departures': return stats.monthly_departures
      case 'departure-comparison': return stats.monthly_departure_comparison
      case 'departures-by-dept': return stats.departures_by_dept
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
      const type = chartTypes[chartId] || 'pie'; const data = getChartData(chartId)
      if (!data || data.length === 0) { opts[chartId] = {}; return }
      if (chartId === 'hires-by-dept') { opts[chartId] = buildGroupedBarOption(data as MonthlyByDeptItem[]) }
      else if (chartId === 'departure-comparison') { opts[chartId] = buildComparisonOption(data as MonthlyComparisonItem[]) }
      else if (chartId === 'dept-ranking') { opts[chartId] = buildHorizontalBarOption(data as DistributionItem[]) }
      else if (chartId === 'departures-by-dept') { opts[chartId] = buildDistributionBarOption(data as DistributionItem[]) }
      else if (type === 'pie') { opts[chartId] = buildPieOption(data as DistributionItem[]) }
      else if (chartId === 'monthly-departures') { const d = data as MonthlyItem[]; opts[chartId] = buildBarOption(d.map(r => r.month), d.map(r => r.value), PALETTE[8]) }
      else if (chartId === 'monthly-hires') { const d = data as MonthlyItem[]; opts[chartId] = buildBarOption(d.map(r => r.month), d.map(r => r.value), PALETTE[2]) }
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
    <div className="space-y-6 pb-8">
      {/* 标题栏 */}
      <div className="flex justify-between items-center animate-fade-in-up">
        <div>
          <h1 className="text-[24px] font-bold tracking-tight" style={{ color: T.ink }}>人事数据看板</h1>
          <p className="text-sm mt-0.5" style={{ color: T.steel }}>员工结构 · 入职离职 · 多维分析</p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)} disabled={availableTypes.length === 0} size="large" style={{ borderRadius: 10 }}>
          添加卡片
        </Button>
      </div>

      {/* KPI 卡片 + 倒计时 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <KpiCard title={`当前在职 · 均龄${summary.age_avg}岁`} value={summary.total_employees} icon={<TeamOutlined />} accent={T.blue} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCard title="本月入职人数" value={summary.new_hires_this_month} icon={<UserAddOutlined />} accent={T.success} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCard title="本月离职人数" value={summary.departures_this_month} icon={<UserDeleteOutlined />} accent={T.error} />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <CountdownCard />
        </Col>
      </Row>

      {/* 图表网格 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {chartOrder.map((chartId, idx) => {
          const config = STAT_TYPE_MAP[chartId]; if (!config) return null
          const isPreset = PRESET_IDS.includes(chartId)
          const cols = chartWidths[chartId] || 2; const height = chartHeights[chartId] || DEFAULT_H
          const isDragging = dragIndex === idx; const isOver = dragOverIndex === idx && dragIndex !== idx
          const data = getChartData(chartId); const option = chartOptions[chartId]

          return (
            <div key={chartId} draggable
              onDragStart={() => onDragStart(idx)} onDragOver={e => onDragOver(e, idx)}
              onDrop={e => onDrop(e, idx)} onDragEnd={onDragEnd}
              className={`${cols === 2 ? 'md:col-span-2' : ''} animate-fade-in-up`}
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
                        {cols === 1 ? '半宽' : '全宽'}
                      </span>
                    </div>
                  }
                  extra={
                    <div className="flex items-center gap-2">
                      <Segmented size="small" value={chartTypes[chartId] || config.defaultType}
                        onChange={v => setChartTypes(prev => ({ ...prev, [chartId]: v as ChartType }))}
                        options={[
                          { label: <><PieChartOutlined style={{ marginRight: 4 }} />饼图</>, value: 'pie' },
                          { label: <><BarChartOutlined style={{ marginRight: 4 }} />柱状图</>, value: 'bar' },
                        ]} />
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
            const isPie = t.defaultType === 'pie'; const accent = isPie ? '#7b3ff2' : T.blue
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
