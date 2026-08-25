'use client'

import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import type { CSSProperties } from 'react'
import { DatePicker, Input, Button, App } from 'antd'
import type { ScheduleViewItem, StageConfigItem } from '@/types/production'
import { schedulePlanItem, updatePlanItem, deletePlanItem } from '@/actions/production'
import dayjs, { type Dayjs } from 'dayjs'

interface Props {
  items: ScheduleViewItem[]
  planOrderId?: string
  productId?: string
  onRefresh: () => void
  dateRange?: [dayjs.Dayjs, dayjs.Dayjs]
  /** 搜索选中的计划项 id，对应卡片高亮、其余淡化 */
  matchedItemIds?: string[]
}

// 搜索命中关键词高亮：把 text 中匹配 keywords 的子串包成黄底 mark
function HighlightMatch({ text, keywords }: { text: string; keywords: string[] }) {
  const parts = useMemo(() => {
    if (!text || keywords.length === 0) return [{ t: text, hit: false }]
    const escaped = keywords.filter(Boolean).map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    if (escaped.length === 0) return [{ t: text, hit: false }]
    const regex = new RegExp(`(${escaped.join('|')})`, 'gi')
    const out: { t: string; hit: boolean }[] = []
    let last = 0
    for (const m of text.matchAll(regex)) {
      if (m.index > last) out.push({ t: text.slice(last, m.index), hit: false })
      out.push({ t: m[0], hit: true })
      last = m.index + m[0].length
    }
    if (last < text.length) out.push({ t: text.slice(last), hit: false })
    return out
  }, [text, keywords])

  return (
    <>
      {parts.map((p, i) =>
        p.hit
          ? (
            <mark
              key={i}
              style={{
                background: '#FEF08A', color: '#854D0E',
                borderRadius: 3, padding: '0 2px',
              }}
            >
              {p.t}
            </mark>
          )
          : <span key={i}>{p.t}</span>
      )}
    </>
  )
}

interface LaneItem extends ScheduleViewItem {
  laneIndex: number
}

// 泳道分配算法
function assignLanes(items: ScheduleViewItem[]): { laneItems: LaneItem[]; totalLanes: number } {
  const sorted = [...items]
    .filter((i) => i.planned_start && i.planned_end)
    .sort((a, b) => dayjs(a.planned_start!).valueOf() - dayjs(b.planned_start!).valueOf())

  const lanes: dayjs.Dayjs[] = []

  const laneItems = sorted.map((item) => {
    const start = dayjs(item.planned_start!)
    let laneIndex = -1
    for (let i = 0; i < lanes.length; i++) {
      if (lanes[i].isBefore(start) || lanes[i].isSame(start)) {
        laneIndex = i
        break
      }
    }
    if (laneIndex === -1) {
      laneIndex = lanes.length
      lanes.push(dayjs(item.planned_end!))
    } else {
      const itemEnd = dayjs(item.planned_end!)
      if (itemEnd.isAfter(lanes[laneIndex])) {
        lanes[laneIndex] = itemEnd
      }
    }
    return { ...item, laneIndex }
  })
  return { laneItems, totalLanes: lanes.length }
}

const STATUS_COLORS: Record<string, string> = {
  draft: '#d4c5f0',
  scheduled: '#b09ae0',
  allocated: '#8b6fd4',
  in_progress: '#5645d4',
  completed: '#9f94c7',
  cancelled: '#a4a097',
}

const STATUS_LABELS: Record<string, string> = {
  in_progress: '进行中',
  scheduled: '已排程',
  completed: '已完成',
  cancelled: '已取消',
  draft: '草稿',
  allocated: '已分配',
}

function hexToRgba(hex: string, a: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${a})`
}

const READONLY_ORDER_STATUSES = new Set(['released', 'completed'])

const LANE_HEIGHT = 28
const LANE_GAP = 8
const HEADER_HEIGHT = 72
const DAY_WIDTH_PX = 36

export function ScheduleCardSwimlane({ items, planOrderId, productId, onRefresh, dateRange, matchedItemIds }: Props) {
  const { message, modal } = App.useApp()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingValues, setEditingValues] = useState<{
    planned_start?: string
    planned_end?: string
    equipment_id?: string
    batch_no?: string
  }>({})
  const [saving, setSaving] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 搜索选中项集合（未选中时为空 Set，全部卡片正常显示）
  const matchedSet = useMemo(() => new Set(matchedItemIds ?? []), [matchedItemIds])

  // 计划项 id→对象 Map，避免 matchedKeywords 中 O(M*N) 的 .find()
  const itemMap = useMemo(() => new Map(items.map((i) => [i.item_id, i])), [items])

  // 命中的关键词（选中计划项的批号 + 产品名），供卡片内文本标黄使用
  const matchedKeywords = useMemo(() => {
    const kws = new Set<string>()
    for (const id of matchedSet) {
      const it = itemMap.get(id)
      if (!it) continue
      if (it.batch_no) kws.add(it.batch_no)
      if (it.product_name) kws.add(it.product_name)
    }
    return [...kws]
  }, [matchedSet, itemMap])

  // 时间轴范围：以选择的日期范围为基准，若排程项超出则自动扩展
  const { timelineStart, timelineEnd, totalDays } = useMemo(() => {
    let start: dayjs.Dayjs
    let end: dayjs.Dayjs
    if (dateRange) {
      start = dateRange[0].startOf('month')
      end = dateRange[1].endOf('month')
    } else {
      const now = dayjs()
      start = now.subtract(1, 'month').startOf('month')
      end = now.add(1, 'month').endOf('month')
    }

    for (const item of items) {
      if (item.planned_start && item.planned_end) {
        const s = dayjs(item.planned_start)
        const e = dayjs(item.planned_end)
        if (s.isBefore(start)) start = s.startOf('month')
        if (e.isAfter(end)) end = e.endOf('month').add(1, 'day')
      }
    }

    const days = end.diff(start, 'day') + 1
    return { timelineStart: start, timelineEnd: end, totalDays: days }
  }, [items, dateRange])

  // 过滤 + 分配泳道
  const { laneItems, totalLanes, unscheduledItems } = useMemo(() => {
    let filtered = planOrderId
      ? items.filter((i) => i.plan_order_id === planOrderId)
      : items
    if (productId && !planOrderId) {
      filtered = filtered.filter((i) => i.product_id === productId)
    }
    const scheduled = filtered.filter((i) => i.planned_start && i.planned_end)
    const unscheduled = filtered.filter((i) => !i.planned_start || !i.planned_end)
    const { laneItems, totalLanes } = assignLanes(scheduled)
    return { laneItems, totalLanes, unscheduledItems: unscheduled }
  }, [items, planOrderId, productId])

  // 内层内容总宽度（px），保证 header 和 body 天然对齐
  const innerWidthPx = Math.max(totalDays * DAY_WIDTH_PX, 800)

  // 生成月份刻度
  const monthTicks = useMemo(() => {
    const ticks: { label: string; leftPx: number; widthPx: number }[] = []
    let cursor = timelineStart.startOf('month')
    while (cursor.isBefore(timelineEnd) || cursor.isSame(timelineEnd, 'month')) {
      const monthStart = cursor
      const monthEnd = cursor.endOf('month')
      const leftPx = monthStart.diff(timelineStart, 'day') * DAY_WIDTH_PX
      const days = monthEnd.diff(monthStart, 'day') + 1
      ticks.push({
        label: cursor.format('YYYY-MM'),
        leftPx,
        widthPx: days * DAY_WIDTH_PX,
      })
      cursor = cursor.add(1, 'month')
    }
    return ticks
  }, [timelineStart, timelineEnd])

  // 周末列位置（背景着色）
  const weekendCols = useMemo(() => {
    const cols: { leftPx: number; widthPx: number }[] = []
    let rangeStart = -1
    for (let d = 0; d <= totalDays; d++) {
      const dow = timelineStart.add(d, 'day').day()
      const isWeekend = dow === 0 || dow === 6
      if (isWeekend && rangeStart === -1) {
        rangeStart = d
      } else if (!isWeekend && rangeStart !== -1) {
        cols.push({ leftPx: rangeStart * DAY_WIDTH_PX, widthPx: (d - rangeStart) * DAY_WIDTH_PX })
        rangeStart = -1
      }
    }
    if (rangeStart !== -1) {
      cols.push({ leftPx: rangeStart * DAY_WIDTH_PX, widthPx: (totalDays + 1 - rangeStart) * DAY_WIDTH_PX })
    }
    return cols
  }, [timelineStart, totalDays])

  // 今日线位置（px）—— 置于今天所在格子的中心（区间），而非起始边界
  const todayPx = useMemo(() => {
    const today = dayjs()
    if (today.isBefore(timelineStart) || today.isAfter(timelineEnd)) return -1
    return today.diff(timelineStart, 'day') * DAY_WIDTH_PX + DAY_WIDTH_PX / 2
  }, [timelineStart, timelineEnd])

  // 计算卡片位置（返回 px 值）
  const getCardStyle = useCallback(
    (start: string | null, end: string | null) => {
      if (!start || !end) return { left: 0, width: 0, visible: false }
      const s = dayjs(start)
      const e = dayjs(end)
      const left = Math.max(0, s.diff(timelineStart, 'day') * DAY_WIDTH_PX)
      const right = Math.max(0, e.diff(timelineStart, 'day') * DAY_WIDTH_PX)
      const width = Math.max(40, right - left)
      return { left, width, visible: width > 0 }
    },
    [timelineStart],
  )

  const handleCardClick = (item: ScheduleViewItem) => {
    if (expandedId === item.item_id) {
      setExpandedId(null)
    } else {
      setExpandedId(item.item_id)
      // 始终重置 editingValues，避免只读卡展开时复用上一个可编辑卡的残留值
      if (!READONLY_ORDER_STATUSES.has(item.order_status)) {
        setEditingValues({
          planned_start: item.planned_start ?? undefined,
          planned_end: item.planned_end ?? undefined,
          equipment_id: item.equipment_id ?? undefined,
          batch_no: item.batch_no ?? undefined,
        })
      } else {
        setEditingValues({})
      }
      // 展开后滚动到卡片位置，确保编辑区可见
      requestAnimationFrame(() => {
        const el = scrollRef.current?.querySelector(`[data-card-id="${item.item_id}"]`)
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        }
      })
    }
  }

  const handleSave = useCallback(async () => {
    if (!expandedId) return
    setSaving(true)
    try {
      const r = await schedulePlanItem(expandedId, {
        planned_start: editingValues.planned_start,
        planned_end: editingValues.planned_end,
        equipment_id: editingValues.equipment_id,
      })
      if (!r.success) { message.error(r.error); return }
      // batch_no 走 updatePlanItem（schedule 接口不支持）
      if (editingValues.batch_no !== undefined) {
        const r2 = await updatePlanItem(expandedId, { batch_no: editingValues.batch_no })
        if (!r2.success) { message.error(r2.error); return }
      }
      message.success('已保存')
      setExpandedId(null)
      onRefresh()
    } finally {
      setSaving(false)
    }
  }, [expandedId, editingValues, message, onRefresh])

  const handleDelete = useCallback(async () => {
    if (!expandedId) return
    modal.confirm({
      title: '确认删除',
      content: '删除后不可恢复，确定删除此计划项？',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        const r = await deletePlanItem(expandedId)
        if (r.success) {
          message.success('已删除')
          setExpandedId(null)
          onRefresh()
        } else {
          message.error(r.error)
        }
      },
    })
  }, [expandedId, modal, message, onRefresh])

  // 滚轮横向滚动：普通滚轮→时间轴左右，Shift+滚轮→泳道上下
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (e.shiftKey) {
        e.preventDefault()
        el.scrollTop += e.deltaY
      } else {
        e.preventDefault()
        el.scrollLeft += e.deltaY
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // 点击外部收起
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.closest('[data-card-id]') || target.closest('.ant-picker-dropdown') || target.closest('.ant-select-dropdown')) {
        return
      }
      setExpandedId(null)
    }
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [])

  const contentHeight = totalLanes * (LANE_HEIGHT + LANE_GAP) + LANE_GAP

  return (
    <>
    <div className="flex-1 min-h-0 flex flex-col rounded-lg border border-[var(--color-hairline)] bg-white shadow-sm overflow-hidden">
      {/* 空状态 */}
      {laneItems.length === 0 && unscheduledItems.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-[var(--color-stone)] text-sm bg-[var(--color-surface-soft)]">
          暂无排程数据
        </div>
      )}

      {/* 统一滚动容器 — 头部(sticky) + 泳道共用一个 scroll，永不偏移 */}
      <div ref={scrollRef} className="flex-1 overflow-auto swimlane-scroll">
        <div style={{ width: innerWidthPx, minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
          {/* 时间轴头部 — sticky 顶部 */}
          <div className="sticky top-0 z-[5] border-b border-[var(--color-hairline)]" style={{
            height: HEADER_HEIGHT,
            background: 'linear-gradient(180deg, #fff 0%, #fafaf9 100%)',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          }}>
            <svg width={innerWidthPx} height={HEADER_HEIGHT} style={{ display: 'block' }}>
              {/* 日刻度 */}
              {Array.from({ length: totalDays + 1 }, (_, i) => {
                const x = i * DAY_WIDTH_PX
                const currentDay = timelineStart.add(i, 'day')
                const dayOfMonth = currentDay.date()
                const isFirst = dayOfMonth === 1
                const showLabel = true
                return (
                  <g key={i}>
                    <line
                      x1={x}
                      y1={isFirst ? 36 : 48}
                      x2={x}
                      y2={HEADER_HEIGHT}
                      stroke={isFirst ? '#c8c4be' : '#ede9e4'}
                      strokeWidth={isFirst ? 1 : 0.5}
                    />
                    {showLabel && i < totalDays && (
                      <text x={x + DAY_WIDTH_PX / 2} y={44} textAnchor="middle" fill="#a4a097" fontSize={10}>
                        {dayOfMonth}
                      </text>
                    )}
                  </g>
                )
              })}
              {/* 月份标签 */}
              {monthTicks.map((tick) => (
                <g key={tick.label}>
                  <text
                    x={tick.leftPx + tick.widthPx / 2}
                    y={16}
                    textAnchor="middle"
                    fill="#5d5b54"
                    fontSize={13}
                    fontWeight={600}
                  >
                    {tick.label}
                  </text>
                </g>
              ))}
              {/* 今日线 */}
              {todayPx >= 0 && (
                <>
                  <rect x={todayPx - 16} y={2} width={32} height={18} rx={9} fill="#e03131" opacity={0.12} />
                  <line x1={todayPx} y1={24} x2={todayPx} y2={HEADER_HEIGHT} stroke="#e03131" strokeWidth={2} opacity={0.7} />
                  <text x={todayPx} y={15} textAnchor="middle" fill="#e03131" fontSize={10} fontWeight={700}>今天</text>
                </>
              )}
            </svg>
          </div>

          {/* 泳道卡片区域 — flex-1 填满，minHeight 保证卡片不重叠 */}
          <div className="relative flex-1" style={{ minHeight: contentHeight || 1 }}>
            {/* 日刻度背景网格 — 填满 */}
            <svg
              style={{
                position: 'absolute', top: 0, left: 0,
                width: '100%', height: '100%',
                pointerEvents: 'none',
              }}
            >
              {Array.from({ length: totalDays + 1 }, (_, i) => {
                const x = i * DAY_WIDTH_PX
                const currentDay = timelineStart.add(i, 'day')
                const isFirstOfMonth = currentDay.date() === 1
                return (
                  <line
                    key={i}
                    x1={x} y1={0} x2={x} y2={contentHeight}
                    stroke={isFirstOfMonth ? '#c8c4be' : '#ede9e4'}
                    strokeWidth={isFirstOfMonth ? 1 : 0.5}
                  />
                )
              })}
              {todayPx >= 0 && (
                <line
                  x1={todayPx} y1={0} x2={todayPx} y2={contentHeight}
                  stroke="#e03131" strokeWidth={1} strokeDasharray="4 3" opacity={0.3}
                />
              )}
              {/* 周末列背景 */}
              {weekendCols.map((wc, wi) => (
                <rect key={wi} x={wc.leftPx} y={0} width={wc.widthPx} height={contentHeight} fill="#f6f5f4" opacity={0.6} />
              ))}
            </svg>

            {/* 泳道背景行 */}
            {Array.from({ length: totalLanes }, (_, li) => (
              <div
                key={li}
                style={{
                  position: 'absolute',
                  top: li * (LANE_HEIGHT + LANE_GAP) + LANE_GAP,
                  left: 0, width: innerWidthPx, height: LANE_HEIGHT,
                  backgroundColor: li % 2 === 0 ? 'transparent' : 'rgba(246, 245, 244, 0.55)',
                  borderRadius: 4,
                }}
              />
            ))}

            {/* 搜索聚焦 — 背景网格极淡置灰，让未匹配内容自然退后（卡片层之上不受影响） */}
            {matchedSet.size > 0 && (
              <div style={{
                position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
                background: 'rgba(255, 255, 255, 0.45)',
                pointerEvents: 'none',
                transition: 'opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
              }} />
            )}

            {/* 卡片 */}
            {laneItems.map((item) => {
              const card = getCardStyle(item.planned_start, item.planned_end)
              if (!card.visible) return null
              const isExpanded = expandedId === item.item_id
              const isReadonly = READONLY_ORDER_STATUSES.has(item.order_status)
              const statusColor = STATUS_COLORS[item.item_status] ?? '#a4a097'
              const isMatched = matchedSet.has(item.item_id)
              const isDimmed = matchedSet.size > 0 && !isMatched && !isExpanded
              const insetBar = `inset 0 3px 0 0 ${statusColor}`
              const hoverShadow = `0 4px 12px rgba(0,0,0,0.08), ${insetBar}`
              const restShadow = `0 1px 3px rgba(0,0,0,0.04), ${insetBar}`
              const expandedShadow = `0 8px 32px ${hexToRgba(statusColor, 0.18)}, ${insetBar}`
              // 靛蓝聚焦：品牌色边框 + 柔和扩散光晕
              const matchedShadow = `0 0 0 3px rgba(99, 102, 241, 0.2), 0 4px 12px rgba(99, 102, 241, 0.15), ${insetBar}`
              // 供 matchPulse 动画读取顶部分隔条颜色
              const cardVars = { '--card-status-color': statusColor } as CSSProperties

              return (
                <div
                  key={item.item_id}
                  data-card-id={item.item_id}
                  style={{
                    ...cardVars,
                    position: 'absolute',
                    top: item.laneIndex * (LANE_HEIGHT + LANE_GAP) + LANE_GAP,
                    left: card.left,
                    width: isExpanded ? 380 : card.width,
                    minWidth: isExpanded ? 380 : 36,
                    background: isExpanded ? '#fff'
                      : isMatched ? 'linear-gradient(180deg, rgba(99, 102, 241, 0.08), rgba(99, 102, 241, 0.02))'
                      : isReadonly ? 'rgba(246, 245, 244, 0.6)'
                      : 'rgba(255, 255, 255, 0.92)',
                    backdropFilter: isExpanded ? 'none' : isReadonly ? 'none' : 'blur(8px)',
                    border: `1px solid ${isExpanded ? statusColor : '#ede9e4'}`,
                    borderRadius: 8,
                    padding: isExpanded ? '10px 14px' : '5px 10px',
                    cursor: 'pointer',
                    opacity: isDimmed ? 0.4 : isReadonly ? 0.65 : 1,
                    transform: isMatched ? 'translateY(-1px)' : undefined,
                    boxShadow: isMatched && !isExpanded
                      ? matchedShadow
                      : isExpanded
                        ? expandedShadow
                        : restShadow,
                    zIndex: isExpanded ? 20 : isMatched ? 10 : 1,
                    transition: 'top 0.35s cubic-bezier(0.4, 0, 0.2, 1), left 0.35s cubic-bezier(0.4, 0, 0.2, 1), width 0.3s cubic-bezier(0.4, 0, 0.2, 1), min-width 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1), transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.25s cubic-bezier(0.4, 0, 0.2, 1), background 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                    // 首次匹配时脉冲呼吸 2 次后静止（取消再选中会重新触发）
                    animation: isMatched && !isExpanded
                      ? 'matchPulse 1.2s ease-out 2'
                      : 'cardEnter 0.35s cubic-bezier(0.4, 0, 0.2, 1) both',
                  }}
                  onClick={(e) => { e.stopPropagation(); handleCardClick(item) }}
                  onMouseEnter={(e) => {
                    if (isExpanded || isMatched) return
                    e.currentTarget.style.transform = 'translateY(-1px)'
                    e.currentTarget.style.boxShadow = hoverShadow
                    if (isDimmed) e.currentTarget.style.opacity = '0.8'
                  }}
                  onMouseLeave={(e) => {
                    if (isExpanded || isMatched) return
                    e.currentTarget.style.transform = ''
                    e.currentTarget.style.boxShadow = restShadow
                    if (isDimmed) e.currentTarget.style.opacity = '0.4'
                  }}
                >
                  {/* 收起态 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {item.batch_no && (
                      <span style={{ fontSize: 12, fontWeight: 600, color: isMatched ? '#6366F1' : 'var(--color-charcoal)', flexShrink: 0 }}>
                        #<HighlightMatch text={item.batch_no} keywords={matchedKeywords} />
                      </span>
                    )}
                    {/* ≤5 天的卡片省略日期文本 */}
                    {(!item.planned_start || !item.planned_end || dayjs(item.planned_end).diff(dayjs(item.planned_start), 'day') > 5) && (
                      <span style={{ fontSize: 11, color: 'var(--color-steel)', whiteSpace: 'nowrap' }}>
                        {item.planned_start ? dayjs(item.planned_start).format('MM/DD') : '?'}
                        {' - '}
                        {item.planned_end ? dayjs(item.planned_end).format('MM/DD') : '?'}
                      </span>
                    )}
                    <span
                      style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: statusColor, flexShrink: 0, marginLeft: 'auto' }}
                      title={STATUS_LABELS[item.item_status] ?? item.item_status}
                    />
                  </div>
                  {/* 工段条 — 仅收起态显示 */}
                  {!isExpanded && item.stage_durations && item.stage_durations.length > 0 && (
                    <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, display: 'flex', height: 4, gap: 1 }}>
                      {item.stage_durations.map((stage: StageConfigItem, idx: number) => (
                        <div
                          key={`${stage.stage_name}-${idx}`}
                          title={`${stage.stage_name}: ${stage.duration_hours}h`}
                          style={{
                            width: Math.max(2, (stage.duration_hours / 24) * DAY_WIDTH_PX),
                            minWidth: 2,
                            backgroundColor: stage.color,
                            borderRadius: 2,
                          }}
                        />
                      ))}
                    </div>
                  )}

                  {/* 展开内容 — grid-template-rows 动画 */}
                  <div
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      display: 'grid',
                      gridTemplateRows: isExpanded ? '1fr' : '0fr',
                      transition: 'grid-template-rows 0.3s cubic-bezier(0.4, 0, 0.2, 1), margin-top 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                      marginTop: isExpanded ? 10 : 0,
                    }}
                  >
                    <div style={{ overflow: 'hidden', minHeight: 0 }}>
                      <div style={{ paddingTop: 10, borderTop: '1px solid #ede9e4', display: 'flex', flexDirection: 'column', gap: 0 }}>
                        {/* 摘要信息 */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, fontSize: 12, color: '#5d5b54' }}>
                          <span style={{ fontWeight: 500, color: '#37352f', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <HighlightMatch text={item.product_name} keywords={matchedKeywords} />
                          </span>
                          {item.planned_quantity != null && (
                            <span style={{ flexShrink: 0 }}>{item.planned_quantity}{item.unit ? ` ${item.unit}` : ''}</span>
                          )}
                          <span style={{
                            flexShrink: 0, fontSize: 11, padding: '1px 8px', borderRadius: 4,
                            backgroundColor: `${statusColor}14`, color: statusColor, fontWeight: 500,
                          }}>
                            {STATUS_LABELS[item.item_status] ?? item.item_status}
                          </span>
                        </div>

                        {/* 工段时间推算 */}
                        {isExpanded && item.stage_durations && item.stage_durations.length > 0 && (item.planned_start || editingValues.planned_start) && (() => {
                          const rows: { stage: StageConfigItem; start: dayjs.Dayjs; end: dayjs.Dayjs }[] = []
                          const baseStart = editingValues.planned_start || item.planned_start
                          let cursor = dayjs(baseStart)
                          for (const s of item.stage_durations) {
                            const end = cursor.add(s.duration_hours, 'hour')
                            rows.push({ stage: s, start: cursor, end })
                            cursor = end
                          }
                          return (
                            <div style={{ marginBottom: 12, padding: '8px 10px', background: '#fafaf9', borderRadius: 6, border: '1px solid #ede9e4' }}>
                              <span style={{ fontSize: 11, color: '#a4a097', fontWeight: 500, display: 'block', marginBottom: 4 }}>工段时间</span>
                              {rows.map(({ stage, start, end }, idx: number) => (
                                <div key={`${stage.stage_name}-${idx}`} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                                  <span style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: stage.color, flexShrink: 0 }} />
                                  <span style={{ fontSize: 11, color: '#37352f', flex: 1 }}>{stage.stage_name}</span>
                                  <span style={{ fontSize: 10, color: '#a4a097' }}>
                                    {start.format('MM/DD HH:mm')} ~ {end.format('MM/DD HH:mm')}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )
                        })()}

                        {/* 编辑字段 — 只读时禁用 */}
                        {!isReadonly && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                              <span style={{ fontSize: 11, color: '#a4a097', fontWeight: 500 }}>计划开始</span>
                              <DatePicker size="small" value={editingValues.planned_start ? dayjs(editingValues.planned_start) : null}
                                onChange={(d: Dayjs | null) => setEditingValues((v) => ({ ...v, planned_start: d?.toISOString() }))}
                                style={{ width: '100%' }} showTime={{ format: 'HH:mm' }} />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                              <span style={{ fontSize: 11, color: '#a4a097', fontWeight: 500 }}>计划结束</span>
                              <DatePicker size="small" value={editingValues.planned_end ? dayjs(editingValues.planned_end) : null}
                                onChange={(d: Dayjs | null) => setEditingValues((v) => ({ ...v, planned_end: d?.toISOString() }))}
                                style={{ width: '100%' }} showTime={{ format: 'HH:mm' }} />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                              <span style={{ fontSize: 11, color: '#a4a097', fontWeight: 500 }}>批次号</span>
                              <Input size="small" value={editingValues.batch_no ?? ''}
                                onChange={(e) => setEditingValues((v) => ({ ...v, batch_no: e.target.value }))}
                                style={{ width: '100%' }} placeholder="输入批次号" />
                            </div>
                          </div>
                        )}

                        {/* 操作按钮 */}
                        <div style={{ display: 'flex', justifyContent: isReadonly ? 'flex-end' : 'space-between', gap: 8, marginTop: 12 }}>
                          {!isReadonly && (
                            <Button size="small" danger onClick={handleDelete}>删除</Button>
                          )}
                          <div style={{ display: 'flex', gap: 8 }}>
                            <Button size="small" onClick={() => setExpandedId(null)}>{isReadonly ? '关闭' : '取消'}</Button>
                            {!isReadonly && (
                              <Button size="small" type="primary" loading={saving} onClick={handleSave}>保存</Button>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>

    {/* 待排程项 */}
    {unscheduledItems.length > 0 && (
      <div className="mt-3 border border-[var(--color-hairline-soft)] rounded-lg p-2.5 px-4 bg-[var(--color-surface-soft)]">
        <span className="text-[13px] font-semibold text-[var(--color-slate)]">
          ⚠ 待排程（{unscheduledItems.length}）：
        </span>
        <div className="flex flex-wrap gap-1.5 mt-1.5">
          {unscheduledItems.map((item) => {
            const isMatched = matchedSet.has(item.item_id)
            return (
              <span
                key={item.item_id}
                className="text-xs text-[var(--color-steel)] bg-white border border-[var(--color-hairline)] rounded px-2 py-0.5"
                style={isMatched
                  ? { borderColor: '#6366F1', color: '#6366F1', fontWeight: 600 }
                  : matchedSet.size > 0 ? { opacity: 0.4 } : undefined}
              >
                {item.batch_no ? `#${item.batch_no} ` : ''}<HighlightMatch text={item.product_name} keywords={matchedKeywords} />
              </span>
            )
          })}
        </div>
      </div>
    )}
    </>
  )
}

