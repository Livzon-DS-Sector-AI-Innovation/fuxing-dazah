'use client'

import { useState, useMemo, useCallback, useEffect } from 'react'
import { Gantt, Willow, Editor, Toolbar } from '@svar-ui/react-gantt'
import '@svar-ui/react-gantt/all.css'
import type { IApi } from '@svar-ui/react-gantt'
import { App, Modal } from 'antd'
import type { ScheduleViewItem } from '@/types/production'
import { deletePlanItem, schedulePlanItem } from '@/actions/production'
import dayjs from 'dayjs'

interface Props {
  items: ScheduleViewItem[]
  planOrderId?: string
  productName?: string
  onRefresh: () => void
}

export function ScheduleGanttNew({ items, planOrderId, productName, onRefresh }: Props) {
  const [mounted, setMounted] = useState(false)
  const [api, setApi] = useState<IApi | null>(null)
  const { message } = App.useApp()

  useEffect(() => { setMounted(true) }, [])

  // Build SVAR task tree: summary order → child items
  const tasks = useMemo(() => {
    const orderMap = new Map<string, {
      order_no: string; order_title: string; items: ScheduleViewItem[]
    }>()

    for (const si of items) {
      if (planOrderId && si.plan_order_id !== planOrderId) continue
      if (productName && si.product_name !== productName) continue
      if (!orderMap.has(si.plan_order_id)) {
        orderMap.set(si.plan_order_id, {
          order_no: si.order_no, order_title: si.order_title, items: [],
        })
      }
      orderMap.get(si.plan_order_id)!.items.push(si)
    }

    const result: any[] = []
    for (const [orderId, order] of orderMap) {
      const summaryId = `summary-${orderId}`
      result.push({
        id: summaryId,
        text: `${order.order_no} ${order.order_title}`,
        type: 'summary',
        open: true,
      })
      for (const si of order.items) {
        result.push({
          id: si.item_id,
          text: si.product_name,
          start: si.planned_start ? new Date(si.planned_start) : undefined,
          end: si.planned_end ? new Date(si.planned_end) : undefined,
          type: 'task',
          parent: summaryId,
          // custom fields for columns & editor
          product_name: si.product_name,
          equipment_id: si.equipment_id,
          planned_quantity: si.planned_quantity,
          unit: si.unit,
          batch_no: si.batch_no,
          item_status: si.item_status,
          item_priority: si.item_priority,
        })
      }
    }
    return result
  }, [items, planOrderId, productName])

  // Persist drag/resize changes to backend
  const handleTaskChange = useCallback(async (ev: { id: string; task: any; inProgress?: boolean }) => {
    if (ev.inProgress) return
    const { id, task } = ev
    if (!id || id.startsWith('summary-')) return
    const planned_start = task.start ? dayjs(task.start).toISOString() : undefined
    const planned_end = task.end ? dayjs(task.end).toISOString() : undefined
    if (!planned_start && !planned_end) return
    const r = await schedulePlanItem(id, { planned_start, planned_end, equipment_id: task.equipment_id })
    if (r.success) { message.success('排程已更新'); onRefresh() }
    else { message.error(r.error); onRefresh() }
  }, [message, onRefresh])

  // Delete with confirmation
  const handleTaskDelete = useCallback(async (ev: { id: string }) => {
    const { id } = ev
    if (!id || id.startsWith('summary-')) return
    Modal.confirm({
      title: '删除计划项',
      content: '确定删除此计划项？',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        const r = await deletePlanItem(id)
        if (r.success) { message.success('已删除'); onRefresh() }
        else { message.error(r.error); onRefresh() }
      },
    })
  }, [message, onRefresh])

  // SSR guard
  if (!mounted) {
    return <div className="min-h-[500px] w-full border border-[var(--color-hairline)] rounded-lg flex items-center justify-center text-[var(--color-stone)]">加载中...</div>
  }

  if (tasks.length === 0) {
    return (
      <div className="h-full min-h-[500px] border border-[var(--color-hairline)] rounded-lg flex items-center justify-center text-[var(--color-stone)]">
        暂无排程数据
      </div>
    )
  }

  return (
    <div className="h-full w-full border border-[var(--color-hairline)] rounded-lg overflow-hidden">
      <Willow>
        <Toolbar api={api ?? undefined} />
        <Gantt
          tasks={tasks}
          init={setApi}
          onTaskChange={handleTaskChange}
          onTaskDelete={handleTaskDelete}
          columns={[
            { id: 'text', header: '计划项', width: 200, flexgrow: 1 },
            {
              id: 'planned_quantity', header: '数量', width: 80,
              getter: (t: any) => t.planned_quantity != null ? `${t.planned_quantity}${t.unit ?? ''}` : '',
            },
            {
              id: 'batch_no', header: '批次号', width: 100,
              getter: (t: any) => t.batch_no ?? '',
            },
            {
              id: 'equipment_id', header: '设备', width: 80,
              getter: (t: any) => t.equipment_id ?? '',
            },
          ]}
          scales={[
            { unit: 'month', step: 1, format: '%M %Y' },
            { unit: 'day', step: 1, format: '%d' },
          ]}
          cellWidth={40}
          cellHeight={36}
          scaleHeight={50}
        />
        {api && <Editor api={api} />}
      </Willow>
    </div>
  )
}
