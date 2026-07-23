'use client'

import { useMemo, useState, useCallback } from 'react'
import type { ScheduleViewItem } from '@/types/production'
import dayjs from 'dayjs'

type ViewMode = 'day' | 'week' | 'month'

interface GanttOrder {
  plan_order_id: string
  order_no: string
  order_title: string
  order_status: string
  order_scheduled_start: string | null
  order_scheduled_end: string | null
  items: ScheduleViewItem[]
}

interface Props {
  items: ScheduleViewItem[]
  viewMode: ViewMode
  timelineStart: string
  timelineEnd: string
  planOrderId?: string
}

const COLORS = [
  '#1677ff', '#52c41a', '#faad14', '#f5222d', '#722ed1',
  '#13c2c2', '#eb2f96', '#fa8c16', '#2f54eb', '#a0d911',
]

function getColor(equipmentId: string | null): string {
  if (!equipmentId) return '#bfbfbf'
  let hash = 0
  for (let i = 0; i < equipmentId.length; i++) {
    hash = equipmentId.charCodeAt(i) + ((hash << 5) - hash)
  }
  return COLORS[Math.abs(hash) % COLORS.length]
}

const LABEL_WIDTH = 220
const ROW_HEIGHT = 34
const ORDER_ROW_HEIGHT = 42

function getColumnWidth(mode: ViewMode): number {
  switch (mode) {
    case 'day': return 60
    case 'week': return 130
    case 'month': return 40
  }
}

function generateTimeColumns(
  start: dayjs.Dayjs,
  end: dayjs.Dayjs,
  mode: ViewMode,
): { label: string; key: string; isWeekend?: boolean }[] {
  const cols: { label: string; key: string; isWeekend?: boolean }[] = []
  if (mode === 'day') {
    let cur = start.startOf('hour')
    while (cur.isBefore(end) || cur.isSame(end)) {
      cols.push({ label: cur.format('HH:00'), key: cur.toISOString() })
      cur = cur.add(1, 'hour')
    }
  } else {
    let cur = start.startOf('day')
    while (cur.isBefore(end) || cur.isSame(end, 'day')) {
      const dayOfWeek = cur.day()
      cols.push({
        label: cur.format(mode === 'month' ? 'D' : 'MM/DD'),
        key: cur.toISOString(),
        isWeekend: dayOfWeek === 0 || dayOfWeek === 6,
      })
      cur = cur.add(1, 'day')
    }
  }
  return cols
}

export function ScheduleGantt({ items, viewMode, timelineStart, timelineEnd, planOrderId }: Props) {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)

  const orders = useMemo(() => {
    const map = new Map<string, GanttOrder>()
    for (const item of items) {
      if (planOrderId && item.plan_order_id !== planOrderId) continue
      if (!map.has(item.plan_order_id)) {
        map.set(item.plan_order_id, {
          plan_order_id: item.plan_order_id,
          order_no: item.order_no,
          order_title: item.order_title,
          order_status: item.order_status,
          order_scheduled_start: item.order_scheduled_start,
          order_scheduled_end: item.order_scheduled_end,
          items: [],
        })
      }
      map.get(item.plan_order_id)!.items.push(item)
    }
    return Array.from(map.values())
  }, [items, planOrderId])

  const ts = dayjs(timelineStart)
  const te = dayjs(timelineEnd)
  const colWidth = getColumnWidth(viewMode)
  const timeColumns = useMemo(
    () => generateTimeColumns(ts, te, viewMode),
    [viewMode, timelineStart, timelineEnd],
  )
  const totalWidth = timeColumns.length * colWidth

  const pxPerMs = viewMode === 'day'
    ? colWidth / (60 * 60 * 1000)
    : colWidth / (24 * 60 * 60 * 1000)

  const getBarStyle = useCallback(
    (start: string | null, end: string | null) => {
      if (!start || !end) return { left: 0, width: 0, visible: false }
      const s = dayjs(start)
      const e = dayjs(end)
      const left = s.diff(ts, 'millisecond') * pxPerMs
      const width = Math.max(4, e.diff(s, 'millisecond') * pxPerMs)
      // clamp to visible area
      const clampedLeft = Math.max(0, left)
      const clampedRight = Math.min(totalWidth, left + width)
      const clampedWidth = Math.max(0, clampedRight - clampedLeft)
      return { left: clampedLeft, width: clampedWidth, visible: clampedWidth > 0 }
    },
    [ts, pxPerMs, totalWidth],
  )

  const handleItemClick = useCallback((item: ScheduleViewItem) => {
    setSelectedItemId((prev) => prev === item.item_id ? null : item.item_id)
  }, [])

  const formatDate = (d: string | null) => d ? dayjs(d).format('YYYY-MM-DD HH:mm') : '-'

  return (
    <div style={{
      border: '1px solid #e5e3df',
      borderRadius: 8,
      overflow: 'hidden',
      backgroundColor: '#fff',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid #e5e3df',
        backgroundColor: '#f6f5f4',
      }}>
        <div style={{
          width: LABEL_WIDTH,
          minWidth: LABEL_WIDTH,
          padding: '10px 16px',
          fontSize: 13,
          fontWeight: 600,
          color: '#37352f',
          borderRight: '1px solid #e5e3df',
          display: 'flex',
          alignItems: 'center',
        }}>
          计划单 / 计划项
        </div>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <div style={{ display: 'flex', width: totalWidth }}>
            {timeColumns.map((col) => (
              <div
                key={col.key}
                style={{
                  width: colWidth,
                  minWidth: colWidth,
                  textAlign: 'center',
                  fontSize: 11,
                  fontWeight: 500,
                  color: col.isWeekend ? '#a4a097' : '#787671',
                  padding: '10px 0',
                  borderRight: '1px solid #ede9e4',
                  backgroundColor: col.isWeekend ? '#fafaf8' : 'transparent',
                }}
              >
                {col.label}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ display: 'flex' }}>
        {/* Left label panel */}
        <div style={{
          width: LABEL_WIDTH,
          minWidth: LABEL_WIDTH,
          borderRight: '1px solid #e5e3df',
        }}>
          {orders.length === 0 && (
            <div style={{ padding: '40px 16px', textAlign: 'center', color: '#a4a097', fontSize: 13 }}>
              无匹配数据
            </div>
          )}
          {orders.map((order) => (
            <div key={order.plan_order_id}>
              <div style={{
                height: ORDER_ROW_HEIGHT,
                padding: '6px 16px',
                display: 'flex',
                alignItems: 'center',
                borderBottom: '1px solid #e5e3df',
                backgroundColor: '#fafaf9',
                overflow: 'hidden',
              }}>
                <span style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#1a1a1a',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }} title={`${order.order_no} ${order.order_title}`}>
                  {order.order_no} {order.order_title}
                </span>
              </div>
              {order.items.map((item) => (
                <div
                  key={item.item_id}
                  style={{
                    height: ROW_HEIGHT,
                    padding: '2px 16px 2px 28px',
                    display: 'flex',
                    alignItems: 'center',
                    borderBottom: '1px solid #ede9e4',
                    backgroundColor: selectedItemId === item.item_id ? '#e6e0f5' : 'transparent',
                    cursor: 'pointer',
                    transition: 'background-color 0.15s',
                  }}
                  onClick={() => handleItemClick(item)}
                >
                  <span style={{
                    fontSize: 12,
                    color: selectedItemId === item.item_id ? '#4534b3' : '#5d5b54',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }} title={`${item.item_no}. ${item.intermediate_type_name} (${item.planned_quantity}${item.unit})`}>
                    {item.item_no}. {item.intermediate_type_name}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* Right time grid */}
        <div style={{ flex: 1, overflowX: 'auto' }}>
          <div style={{ width: Math.max(totalWidth, 1), position: 'relative' }}>
            {orders.map((order) => (
              <div key={order.plan_order_id}>
                {/* Order row */}
                <div style={{
                  height: ORDER_ROW_HEIGHT,
                  position: 'relative',
                  borderBottom: '1px solid #e5e3df',
                  backgroundColor: '#fafaf9',
                }}>
                  {timeColumns.map((col, ci) => (
                    <div
                      key={col.key}
                      style={{
                        position: 'absolute',
                        left: ci * colWidth,
                        top: 0,
                        width: colWidth,
                        height: '100%',
                        borderRight: '1px solid #ede9e4',
                        backgroundColor: col.isWeekend ? '#fafaf8' : 'transparent',
                      }}
                    />
                  ))}
                  {order.order_scheduled_start && order.order_scheduled_end && (() => {
                    const bar = getBarStyle(order.order_scheduled_start, order.order_scheduled_end)
                    if (!bar.visible) return null
                    return (
                      <div style={{
                        position: 'absolute',
                        top: 8,
                        height: ORDER_ROW_HEIGHT - 16,
                        left: bar.left,
                        width: bar.width,
                        backgroundColor: '#37352f',
                        borderRadius: 4,
                        opacity: 0.15,
                        borderLeft: '3px solid #37352f',
                        minWidth: 4,
                      }} />
                    )
                  })()}
                </div>

                {/* Item rows */}
                {order.items.map((item) => {
                  const bar = getBarStyle(item.planned_start, item.planned_end)
                  const color = getColor(item.equipment_id)
                  const isSelected = selectedItemId === item.item_id
                  return (
                    <div
                      key={item.item_id}
                      style={{
                        height: ROW_HEIGHT,
                        position: 'relative',
                        borderBottom: '1px solid #ede9e4',
                        backgroundColor: isSelected ? '#f0eef6' : 'transparent',
                        cursor: 'pointer',
                        transition: 'background-color 0.15s',
                      }}
                      onClick={() => handleItemClick(item)}
                    >
                      {timeColumns.map((col, ci) => (
                        <div
                          key={col.key}
                          style={{
                            position: 'absolute',
                            left: ci * colWidth,
                            top: 0,
                            width: colWidth,
                            height: '100%',
                            borderRight: '1px solid #ede9e4',
                            backgroundColor: col.isWeekend ? '#fafaf8' : 'transparent',
                          }}
                        />
                      ))}
                      {bar.visible && (
                        <div
                          style={{
                            position: 'absolute',
                            top: 5,
                            height: ROW_HEIGHT - 10,
                            left: bar.left,
                            width: bar.width,
                            backgroundColor: color,
                            borderRadius: 4,
                            opacity: isSelected ? 1 : 0.82,
                            minWidth: 4,
                            display: 'flex',
                            alignItems: 'center',
                            paddingLeft: 6,
                            overflow: 'hidden',
                            boxShadow: isSelected ? '0 1px 4px rgba(0,0,0,0.2)' : undefined,
                          }}
                          title={`${item.intermediate_type_name} | ${item.planned_quantity}${item.unit} | ${formatDate(item.planned_start)} ~ ${formatDate(item.planned_end)}`}
                        >
                          <span style={{
                            fontSize: 11,
                            color: '#fff',
                            fontWeight: 500,
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}>
                            {item.intermediate_type_name}
                          </span>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Selected item detail */}
      {selectedItemId && (() => {
        const item = items.find((i) => i.item_id === selectedItemId)
        if (!item) return null
        return (
          <div style={{
            margin: 16,
            padding: '12px 16px',
            backgroundColor: '#f6f5f4',
            borderRadius: 8,
            display: 'flex',
            gap: 24,
            fontSize: 13,
            color: '#37352f',
            flexWrap: 'wrap' as const,
          }}>
            <span><strong>产品:</strong> {item.intermediate_type_name}</span>
            <span><strong>数量:</strong> {item.planned_quantity}{item.unit}</span>
            <span><strong>设备:</strong> {item.equipment_id || '-'}</span>
            <span><strong>开始:</strong> {formatDate(item.planned_start)}</span>
            <span><strong>结束:</strong> {formatDate(item.planned_end)}</span>
            <span><strong>状态:</strong> {item.item_status}</span>
          </div>
        )
      })()}
    </div>
  )
}
