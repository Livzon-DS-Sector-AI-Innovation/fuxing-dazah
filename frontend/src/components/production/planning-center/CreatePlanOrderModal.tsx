'use client'

import { useEffect } from 'react'
import { App, DatePicker, Form, Input, Modal, Select } from 'antd'
import { createPlanOrder } from '@/actions/production'
import type { CreatePlanOrderInput } from '@/types/production'
import { serializeDates } from './utils'
import { PRIORITY_CONFIG } from './constants'

const PRIORITY_OPTIONS = Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))

interface Props {
  open: boolean
  onClose: () => void
  onSuccess?: () => void
}

export function CreatePlanOrderModal({ open, onClose, onSuccess }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm<CreatePlanOrderInput>()

  useEffect(() => {
    if (open) form.resetFields()
  }, [open, form])

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const input = serializeDates(values as unknown as Record<string, unknown>)
    const r = await createPlanOrder(input as unknown as CreatePlanOrderInput)
    if (r.success) {
      message.success('计划单已创建')
      form.resetFields()
      onSuccess?.()
    } else {
      message.error(r.error)
    }
  }

  return (
    <Modal
      title="新建计划单"
      open={open}
      onOk={handleOk}
      onCancel={() => { form.resetFields(); onClose() }}
      destroyOnHidden
      width={480}
    >
      <Form form={form} layout="vertical" initialValues={{ priority: 'medium' }}>
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input placeholder="例如：2026年Q3生产计划" />
        </Form.Item>
        <Form.Item name="scheduled_start" label="计划开始日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="scheduled_end" label="计划结束日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="priority" label="优先级">
          <Select options={PRIORITY_OPTIONS} />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
