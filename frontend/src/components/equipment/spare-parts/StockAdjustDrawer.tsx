'use client'

import { useState } from 'react'
import { App, Drawer, Form, Input, InputNumber, Button, Space, Typography } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { stockAdjust } from '@/actions/equipment'
import { StockAdjustInput } from '@/types/equipment'

const { TextArea } = Input

interface StockAdjustDrawerProps {
  onRefresh?: () => void
}

export function StockAdjustDrawer({ onRefresh }: StockAdjustDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const {
    stockAdjustDrawerOpen, stockAdjustSparePartId, closeStockAdjustDrawer,
    spareParts,
  } = useEquipmentStore()
  const sparePart = spareParts.find((p) => p.id === stockAdjustSparePartId) ?? null
  const currentQty = sparePart?.current_qty ?? 0

  const handleSubmit = async () => {
    if (!stockAdjustSparePartId || submitting) return
    let values: { new_qty: number; remark?: string }
    try {
      values = await form.validateFields()
    } catch { return }
    const data: StockAdjustInput = {
      new_qty: values.new_qty,
      remark: values.remark || undefined,
    }
    // 盘点按「目标数量」写库存，重复提交会让流水重复记一笔差额
    setSubmitting(true)
    try {
      const result = await stockAdjust(stockAdjustSparePartId, data)
      if (!result.success) { message.error(result.error); return }
      message.success('盘点调整成功')
      closeStockAdjustDrawer()
      onRefresh?.()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title="盘点调整"
      size={480}
      open={stockAdjustDrawerOpen}
      onClose={closeStockAdjustDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeStockAdjustDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>确认调整</Button>
        </Space>
      }
    >
      {sparePart && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {sparePart.code} · {sparePart.name}｜账面库存 <Typography.Text strong>{currentQty}</Typography.Text> {sparePart.unit}
        </Typography.Text>
      )}
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item
          name="new_qty"
          label="盘点后数量"
          extra="与账面一致时不会产生流水"
          rules={[{ required: true, message: '请输入盘点后数量' }]}
        >
          <InputNumber min={0} precision={0} style={{ width: '100%' }} placeholder="请输入实际盘点数量" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <TextArea placeholder="盘点差异原因（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
