'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, InputNumber, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { stockInbound } from '@/actions/equipment'
import { StockInboundInput } from '@/types/equipment'

const { TextArea } = Input

interface StockInboundDrawerProps {
  onRefresh?: () => void
}

export function StockInboundDrawer({ onRefresh }: StockInboundDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { stockInboundDrawerOpen, stockInboundSparePartId, closeStockInboundDrawer } = useEquipmentStore()

  useEffect(() => {
    if (stockInboundDrawerOpen) {
      form.resetFields()
    }
  }, [stockInboundDrawerOpen, form])

  const handleSubmit = async () => {
    if (!stockInboundSparePartId) return
    try {
      const values = await form.validateFields()
      const data: StockInboundInput = {
        quantity: values.quantity,
        warehouse_location: values.warehouse_location || undefined,
        remark: values.remark || undefined,
      }
      await stockInbound(stockInboundSparePartId, data)
      message.success('入库成功')
      closeStockInboundDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    }
  }

  return (
    <Drawer
      title="备件入库"
      size={480}
      open={stockInboundDrawerOpen}
      onClose={closeStockInboundDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeStockInboundDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>确认入库</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item name="quantity" label="入库数量" rules={[{ required: true, message: '请输入入库数量' }]}>
          <InputNumber min={1} precision={0} style={{ width: '100%' }} placeholder="请输入入库数量" />
        </Form.Item>
        <Form.Item name="warehouse_location" label="库位">
          <Input placeholder="请输入库位（可选）" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <TextArea placeholder="备注信息（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
