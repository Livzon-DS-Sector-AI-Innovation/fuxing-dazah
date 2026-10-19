'use client'

import { useState } from 'react'
import { App, Drawer, Form, InputNumber, Button, Space, Typography, Input } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { updateStockSettings } from '@/actions/equipment'
import { fetchSparePartStockClient } from '@/lib/api/equipment-client'
import { StockSettingsInput } from '@/types/equipment'

interface StockSettingsDrawerProps {
  onRefresh?: () => void
}

export function StockSettingsDrawer({ onRefresh }: StockSettingsDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const {
    stockSettingsDrawerOpen, stockSettingsSparePart, closeStockSettingsDrawer,
  } = useEquipmentStore()

  const part = stockSettingsSparePart
  const [currentQty, setCurrentQty] = useState<number | null>(null)

  // 列表行是打开前的快照；按 id 实时拉取并回填，避免用旧值覆盖他人刚改过的设置
  const handleOpenChange = (open: boolean) => {
    if (!open || !part) return
    setCurrentQty(null)
    fetchSparePartStockClient(part.id)
      .then(stock => {
        setCurrentQty(stock.current_qty)
        form.setFieldsValue({
          safety_qty: stock.safety_qty,
          min_order_qty: stock.min_order_qty,
          warehouse_location: stock.warehouse_location ?? undefined,
        })
      })
      .catch(() => { /* 拉取失败沿用列表快照，仍可提交 */ })
  }

  const handleSubmit = async () => {
    if (!part || submitting) return
    let values: StockSettingsInput
    try {
      values = await form.validateFields()
    } catch { return }
    setSubmitting(true)
    try {
      const data: StockSettingsInput = {
        safety_qty: values.safety_qty ?? 0,
        min_order_qty: values.min_order_qty ?? 1,
        // 空串可清空库位；与后端「传 null/空串清空」语义对齐
        warehouse_location: values.warehouse_location ?? '',
      }
      const result = await updateStockSettings(part.id, data)
      if (!result.success) { message.error(result.error); return }
      message.success('库存设置已更新')
      closeStockSettingsDrawer()
      onRefresh?.()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title="库存设置"
      size={480}
      open={stockSettingsDrawerOpen}
      onClose={closeStockSettingsDrawer}
      afterOpenChange={handleOpenChange}
      destroyOnHidden
      styles={{ body: { padding: '16px 24px' } }}
      extra={
        <Space>
          <Button onClick={closeStockSettingsDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>保存</Button>
        </Space>
      }
    >
      {part && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {part.code} · {part.name}｜当前库存{' '}
          <Typography.Text strong>{currentQty ?? part.current_qty}</Typography.Text> {part.unit}
        </Typography.Text>
      )}
      <Form
        form={form}
        layout="vertical"
        requiredMark="optional"
        preserve={false}
        initialValues={part ? {
          safety_qty: part.safety_qty ?? 0,
          min_order_qty: part.min_order_qty ?? 1,
          warehouse_location: part.warehouse_location ?? undefined,
        } : undefined}
        key={part?.id ?? 'settings'}
      >
        <Form.Item
          name="safety_qty"
          label="安全库存"
          extra="当前库存低于该值时触发预警与飞书提醒"
          rules={[{ required: true, message: '请输入安全库存' }]}
        >
          <InputNumber min={0} precision={0} style={{ width: '100%' }} placeholder="0" />
        </Form.Item>
        <Form.Item
          name="min_order_qty"
          label="最小采购批量"
          extra="预警页的「建议补货量」按此批量向上取整"
          rules={[{ required: true, message: '请输入最小采购批量' }]}
        >
          <InputNumber min={1} precision={0} style={{ width: '100%' }} placeholder="1" />
        </Form.Item>
        <Form.Item name="warehouse_location" label="库位" extra="清空后保存即移除库位">
          <Input placeholder="如 A-01（可选）" allowClear />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
