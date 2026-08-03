'use client'

import { useState, useCallback, useMemo } from 'react'
import { DatePicker, Select, Spin, Button, Modal, Input, App } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { PlanOrder, Product } from '@/types/production'
import { fetchScheduleViewClient, fetchPlanOrdersClient, fetchProductsClient } from '@/lib/api/production-client'
import { createPlanItem, schedulePlanItem } from '@/actions/production'
import type { CreatePlanItemInput } from '@/types/production'

import { ScheduleCardSwimlane } from './ScheduleCardSwimlane'
import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'

export function ScheduleView() {
  const queryClient = useQueryClient()
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>(() => {
    const now = dayjs()
    return [now.startOf('month'), now.add(1, 'month').endOf('month')]
  })
  const [productId, setProductId] = useState<string | undefined>()
  const [planOrderId, setPlanOrderId] = useState<string | undefined>()

  const { data: items, isLoading, refetch } = useQuery({
    queryKey: ['scheduleView', dateRange[0].toISOString(), dateRange[1].toISOString()],
    queryFn: () => fetchScheduleViewClient({
      from_time: dateRange[0].toISOString(),
      to_time: dateRange[1].toISOString(),
    }),
    placeholderData: (prev) => prev,
  })

  const { data: products } = useQuery({
    queryKey: ['products'],
    queryFn: () => fetchProductsClient(),
    staleTime: 5 * 60 * 1000,
  })

  const { data: planOrders } = useQuery({
    queryKey: ['planOrders'],
    queryFn: () => fetchPlanOrdersClient({ page_size: 100 }),
    staleTime: 2 * 60 * 1000,
  })

  // ── 新增计划项 ──
  const { message } = App.useApp()
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addLoading, setAddLoading] = useState(false)
  const [addForm, setAddForm] = useState<{
    product_id: string
    product_name: string
    batch_no: string
    planned_start: Dayjs | null
    planned_end: Dayjs | null
  }>({
    product_id: '',
    product_name: '',
    batch_no: '',
    planned_start: null,
    planned_end: null,
  })

  const productFormOptions = useMemo(() => (products ?? []).map((p: Product) => ({
    value: p.id,
    label: p.product_name,
  })), [products])

  const selectedOrderEditable = useMemo(() => {
    if (!planOrderId) return false
    const order = (planOrders ?? []).find((po) => po.id === planOrderId)
    return order ? order.status !== 'released' && order.status !== 'completed' && order.status !== 'closed' : false
  }, [planOrderId, planOrders])

  const handleAdd = useCallback(async () => {
    if (!planOrderId) return
    if (!addForm.product_id || !addForm.batch_no || !addForm.planned_start || !addForm.planned_end) {
      message.warning('请填写产品、批次号、计划开始和结束时间')
      return
    }
    setAddLoading(true)
    try {
      const createResult = await createPlanItem(planOrderId, {
        product_id: addForm.product_id,
        product_name: addForm.product_name,
        batch_no: addForm.batch_no,
      } satisfies CreatePlanItemInput)
      if (!createResult.success) {
        message.error(createResult.error)
        return
      }
      const newItemId = createResult.data!.id
      const scheduleResult = await schedulePlanItem(newItemId, {
        planned_start: addForm.planned_start!.toISOString(),
        planned_end: addForm.planned_end!.toISOString(),
      })
      if (!scheduleResult.success) {
        message.error(scheduleResult.error)
        return
      }
      message.success('已添加计划项')
      setAddModalOpen(false)
      setAddForm({ product_id: '', product_name: '', batch_no: '', planned_start: null, planned_end: null })
      refetch()
    } finally {
      setAddLoading(false)
    }
  }, [planOrderId, addForm, message, refetch])

  const handleDateRangeChange = useCallback((dates: [Dayjs | null, Dayjs | null] | null) => {
    if (dates?.[0] && dates?.[1]) {
      setDateRange([dates[0], dates[1]])
    }
  }, [])

  const productOptions = useMemo(() => (products ?? []).map((p: Product) => ({
    value: p.id,
    label: p.product_name,
  })), [products])

  const planOrderOptions = useMemo(() => {
    let orders = planOrders ?? []
    if (productId) {
      orders = orders.filter((po) => po.product_id === productId)
    }
    return orders.map((po: PlanOrder) => ({
      value: po.id,
      label: po.title,
    }))
  }, [planOrders, productId])

  const onRefresh = useCallback(() => { refetch(); queryClient.invalidateQueries({ queryKey: ['plan-orders'] }); queryClient.invalidateQueries({ queryKey: ['plan-order-detail'] }) }, [refetch, queryClient])

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Filter bar + 工具栏 */}
      <div className="flex items-center gap-3 flex-wrap">
        <DatePicker.RangePicker
          value={dateRange}
          onChange={handleDateRangeChange}
          size="small"
          style={{ width: 240 }}
          picker="month"
        />

        <Select
          placeholder="全部产品"
          allowClear
          showSearch={{ filterOption: (input, option) =>
            (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
          }}
          size="small"
          style={{ width: 220 }}
          value={productId}
          onChange={setProductId}
          options={productOptions}
        />

        <Select
          placeholder="全部计划单"
          allowClear
          showSearch={{ filterOption: (input, option) =>
            (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
          }}
          size="small"
          style={{ width: 220 }}
          value={planOrderId}
          onChange={setPlanOrderId}
          options={planOrderOptions}
        />

        {selectedOrderEditable && (
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => setAddModalOpen(true)}
          >
            新增计划项
          </Button>
        )}
      </div>

      {/* Content — flex-1 min-h-0 flex flex-col 确保子组件能吃到高度 */}
      <div className="flex-1 min-h-0 flex flex-col">
      {isLoading ? (
        <div className="flex justify-center items-center h-full">
          <Spin />
        </div>
      ) : (
        <ScheduleCardSwimlane
          items={items ?? []}
          planOrderId={planOrderId}
          productId={productId}
          onRefresh={onRefresh}
          dateRange={dateRange}
        />
      )}
      </div>

      {/* 新增计划项 Modal */}
      <Modal
        title="新增计划项"
        open={addModalOpen}
        onOk={handleAdd}
        onCancel={() => {
          setAddModalOpen(false)
          setAddForm({ product_id: '', product_name: '', batch_no: '', planned_start: null, planned_end: null })
        }}
        confirmLoading={addLoading}
        okText="确定"
        cancelText="取消"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, color: '#5d5b54' }}>产品 *</span>
            <Select
              placeholder="选择产品"
              showSearch
              value={addForm.product_id || undefined}
              onChange={(_value, option) => {
                const opt = option as { value: string; label: string }
                setAddForm((f) => ({ ...f, product_id: opt.value, product_name: opt.label }))
              }}
              options={productFormOptions}
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, color: '#5d5b54' }}>批次号 *</span>
            <Input
              placeholder="输入批次号"
              value={addForm.batch_no}
              onChange={(e) => setAddForm((f) => ({ ...f, batch_no: e.target.value }))}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, color: '#5d5b54' }}>计划开始 *</span>
            <DatePicker
              value={addForm.planned_start}
              onChange={(d) => setAddForm((f) => ({ ...f, planned_start: d }))}
              showTime={{ format: 'HH:mm' }}
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, color: '#5d5b54' }}>计划结束 *</span>
            <DatePicker
              value={addForm.planned_end}
              onChange={(d) => setAddForm((f) => ({ ...f, planned_end: d }))}
              showTime={{ format: 'HH:mm' }}
              style={{ width: '100%' }}
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
