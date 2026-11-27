'use client'

import { useState } from 'react'
import { App, Drawer, Form, Input, InputNumber, Button, Space, Typography } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { stockInbound } from '@/actions/equipment'
import { fetchSparePartStockClient } from '@/lib/api/equipment-client'
import { StockInboundInput } from '@/types/equipment'

const { TextArea } = Input

interface StockInboundDrawerProps {
  onRefresh?: () => void
}

export function StockInboundDrawer({ onRefresh }: StockInboundDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [currentQty, setCurrentQty] = useState<number | null>(null)
  const {
    stockInboundDrawerOpen, stockInboundSparePartId, closeStockInboundDrawer,
    spareParts,
  } = useEquipmentStore()
  const sparePart = spareParts.find((p) => p.id === stockInboundSparePartId) ?? null

  const handleOpenChange = (open: boolean) => {
    if (open && stockInboundSparePartId) {
      setCurrentQty(null)
      fetchSparePartStockClient(stockInboundSparePartId)
        .then(stock => { setCurrentQty(stock.current_qty) })
        .catch(() => { /* 上下文展示失败不阻塞入库 */ })
    }
  }

  const handleSubmit = async () => {
    if (!stockInboundSparePartId || submitting) return
    let values: { quantity: number; warehouse_location?: string; remark?: string }
    try {
      values = await form.validateFields()
    } catch { return }
    const data: StockInboundInput = {
      quantity: values.quantity,
      warehouse_location: values.warehouse_location || undefined,
      remark: values.remark || undefined,
    }
    // 重复提交会重复入库，加在途状态挡住第二次点击
    setSubmitting(true)
    try {
      const result = await stockInbound(stockInboundSparePartId, data)
      if (!result.success) { message.error(result.error); return }
      message.success(`入库成功，当前库存 ${result.data?.current_qty ?? '-'}`)
      closeStockInboundDrawer()
      onRefresh?.()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title="备件入库"
      size={480}
      open={stockInboundDrawerOpen}
      onClose={closeStockInboundDrawer}
      afterOpenChange={handleOpenChange}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeStockInboundDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>确认入库</Button>
        </Space>
      }
    >
      {sparePart && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {sparePart.code} · {sparePart.name}｜当前库存{' '}
          <Typography.Text strong>{currentQty ?? '…'}</Typography.Text> {sparePart.unit}
          {sparePart.warehouse_location ? `（${sparePart.warehouse_location}）` : ''}
        </Typography.Text>
      )}
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item name="quantity" label="入库数量" rules={[{ required: true, message: '请输入入库数量' }]}>
          <InputNumber min={1} precision={0} style={{ width: '100%' }} placeholder="请输入入库数量" />
        </Form.Item>
        <Form.Item name="warehouse_location" label="库位" extra="留空保持原库位不变">
          <Input placeholder={sparePart?.warehouse_location || '请输入库位（可选）'} allowClear />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <TextArea placeholder="备注信息（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
