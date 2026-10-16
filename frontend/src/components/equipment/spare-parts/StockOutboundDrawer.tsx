'use client'

import { useState } from 'react'
import { App, Drawer, Form, Input, InputNumber, Button, Space, Typography } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { stockOutbound } from '@/actions/equipment'
import { StockOutboundInput } from '@/types/equipment'

const { TextArea } = Input

interface StockOutboundDrawerProps {
  onRefresh?: () => void
}

export function StockOutboundDrawer({ onRefresh }: StockOutboundDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const {
    stockOutboundDrawerOpen, stockOutboundSparePartId, closeStockOutboundDrawer,
    spareParts,
  } = useEquipmentStore()
  // 备件可能不在当前页（列表分页），找不到时不限制上限，由后端兜底校验
  const sparePart = spareParts.find((p) => p.id === stockOutboundSparePartId) ?? null
  const currentQty = sparePart?.current_qty ?? 0

  const handleSubmit = async () => {
    if (!stockOutboundSparePartId || submitting) return
    let values: { quantity: number; remark?: string }
    try {
      values = await form.validateFields()
    } catch { return }
    const data: StockOutboundInput = {
      quantity: values.quantity,
      remark: values.remark || undefined,
    }
    // 出库是「读库存→校验→扣减」，重复提交会重复扣减
    setSubmitting(true)
    try {
      const result = await stockOutbound(stockOutboundSparePartId, data)
      if (!result.success) { message.error(result.error); return }
      message.success('出库成功')
      closeStockOutboundDrawer()
      onRefresh?.()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title="备件出库"
      size={480}
      open={stockOutboundDrawerOpen}
      onClose={closeStockOutboundDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeStockOutboundDrawer}>取消</Button>
          <Button type="primary" danger loading={submitting} onClick={handleSubmit}>确认出库</Button>
        </Space>
      }
    >
      {sparePart && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {sparePart.code} · {sparePart.name}｜当前库存 <Typography.Text strong>{currentQty}</Typography.Text> {sparePart.unit}
        </Typography.Text>
      )}
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item
          name="quantity"
          label="出库数量"
          rules={[{ required: true, message: '请输入出库数量' }]}
        >
          <InputNumber
            min={1}
            max={currentQty > 0 ? currentQty : undefined}
            precision={0}
            style={{ width: '100%' }}
            placeholder="请输入出库数量"
          />
        </Form.Item>
        <Form.Item name="remark" label="备注（用途）">
          <TextArea placeholder="如：车间领用 / 报废 / 调拨（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
