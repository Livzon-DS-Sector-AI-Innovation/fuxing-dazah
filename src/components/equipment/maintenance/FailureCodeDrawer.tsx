'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, InputNumber, Switch, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createFailureCode, updateFailureCode } from '@/actions/equipment'
import { CreateFailureCodeInput, UpdateFailureCodeInput } from '@/types/equipment'

const { TextArea } = Input

const typeLabels: Record<string, string> = {
  symptoms: '故障现象',
  causes: '故障原因',
  actions: '维修措施',
}

interface FailureCodeDrawerProps {
  onRefresh?: () => void
}

export function FailureCodeDrawer({ onRefresh }: FailureCodeDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { failureCodeDrawerOpen, failureCodeDrawerType, editingFailureCode, closeFailureCodeDrawer } = useEquipmentStore()

  useEffect(() => {
    if (failureCodeDrawerOpen) {
      if (editingFailureCode) {
        form.setFieldsValue({
          code: editingFailureCode.code,
          name: editingFailureCode.name,
          description: editingFailureCode.description,
          sort_order: editingFailureCode.sort_order,
          is_active: editingFailureCode.is_active,
        })
      } else {
        form.resetFields()
        form.setFieldsValue({ sort_order: 0, is_active: true })
      }
    }
  }, [failureCodeDrawerOpen, editingFailureCode, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingFailureCode) {
        const data: UpdateFailureCodeInput = {
          code: values.code, name: values.name,
          description: values.description || undefined,
          sort_order: values.sort_order, is_active: values.is_active,
        }
        await updateFailureCode(failureCodeDrawerType, editingFailureCode.id, data)
        message.success('更新成功')
      } else {
        const data: CreateFailureCodeInput = {
          code: values.code, name: values.name,
          description: values.description || undefined,
          sort_order: values.sort_order, is_active: values.is_active,
        }
        await createFailureCode(failureCodeDrawerType, data)
        message.success('创建成功')
      }
      closeFailureCodeDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    }
  }

  const title = `${editingFailureCode ? '编辑' : '新增'}${typeLabels[failureCodeDrawerType] || '故障代码'}`

  return (
    <Drawer
      title={title}
      size={420}
      open={failureCodeDrawerOpen}
      onClose={closeFailureCodeDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeFailureCodeDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>{editingFailureCode ? '保存' : '创建'}</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item name="code" label="代码" rules={[{ required: true, message: '请输入代码' }, { max: 50, message: '代码不超过50个字符' }]}>
          <Input placeholder="例如: NOISE, WEAR, REPLACE" />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }, { max: 100, message: '名称不超过100个字符' }]}>
          <Input placeholder="例如: 异响, 轴承磨损, 更换部件" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <TextArea placeholder="详细描述（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
        <Form.Item name="sort_order" label="排序">
          <InputNumber min={0} style={{ width: '100%' }} placeholder="数值越小越靠前" />
        </Form.Item>
        <Form.Item name="is_active" label="启用状态" valuePropName="checked">
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
