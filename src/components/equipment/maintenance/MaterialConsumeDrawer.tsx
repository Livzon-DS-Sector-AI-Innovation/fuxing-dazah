'use client'

import { useState, useEffect } from 'react'
import { App, Drawer, Form, Select, InputNumber, Button, Space, Empty } from 'antd'
import { PlusOutlined, MinusCircleOutlined } from '@ant-design/icons'
import { consumeMaterials } from '@/actions/equipment'
import { MaterialConsumeInput, SparePart } from '@/types/equipment'

interface MaterialConsumeDrawerProps {
  workOrderId: string
  spareParts: SparePart[]
  onRefresh?: () => void
}

export function MaterialConsumeDrawer({ workOrderId, spareParts, onRefresh }: MaterialConsumeDrawerProps) {
  const { message } = App.useApp()
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    if (open) {
      form.resetFields()
      form.setFieldsValue({ items: [{ spare_part_id: undefined, quantity: 1 }] })
    }
  }, [open, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const items = (values.items || []).filter(
        (item: { spare_part_id?: string; quantity?: number }) => item.spare_part_id && item.quantity
      )
      if (items.length === 0) {
        message.warning('请至少添加一条领料记录')
        return
      }
      setLoading(true)
      const data: MaterialConsumeInput = { items }
      await consumeMaterials(workOrderId, data)
      message.success('领料成功')
      setOpen(false)
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        领料
      </Button>
      <Drawer
        title="工单领料"
        size={480}
        open={open}
        onClose={() => setOpen(false)}
        destroyOnHidden
        extra={
          <Space>
            <Button onClick={() => setOpen(false)}>取消</Button>
            <Button type="primary" loading={loading} onClick={handleSubmit}>确认领料</Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
          <Form.List name="items">
            {(fields, { add, remove }) => (
              <div>
                {fields.map(({ key, name, ...restField }) => (
                  <div key={key} style={{ display: 'flex', gap: 12, marginBottom: 12, alignItems: 'flex-start' }}>
                    <Form.Item
                      {...restField} name={[name, 'spare_part_id']}
                      rules={[{ required: true, message: '请选择备件' }]}
                      style={{ flex: 2, marginBottom: 0 }}
                    >
                      <Select
                        placeholder="选择备件" showSearch optionFilterProp="label"
                        options={spareParts.map((sp) => ({
                          label: `${sp.code} - ${sp.name} (库存: ${sp.current_qty}${sp.unit})`,
                          value: sp.id,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item
                      {...restField} name={[name, 'quantity']}
                      rules={[{ required: true, message: '请输入数量' }]}
                      style={{ flex: 1, marginBottom: 0 }}
                    >
                      <InputNumber min={1} style={{ width: '100%' }} placeholder="数量" />
                    </Form.Item>
                    {fields.length > 1 && (
                      <MinusCircleOutlined
                        style={{ marginTop: 10, color: '#787671', cursor: 'pointer' }}
                        onClick={() => remove(name)}
                      />
                    )}
                  </div>
                ))}
                <Button type="dashed" onClick={() => add()} icon={<PlusOutlined />} style={{ width: '100%' }}>
                  添加备件
                </Button>
              </div>
            )}
          </Form.List>
          {spareParts.length === 0 && (
            <Empty description="暂无可用备件" style={{ marginTop: 24 }} />
          )}
        </Form>
      </Drawer>
    </>
  )
}
