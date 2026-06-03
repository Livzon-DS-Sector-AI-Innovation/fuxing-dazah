'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createWorkOrder } from '@/actions/equipment'
import { CreateWorkOrderInput, FailureCode } from '@/types/equipment'
import { Equipment } from '@/types/equipment'

const { TextArea } = Input

interface WorkOrderDrawerProps {
  equipments: Equipment[]
  symptoms: FailureCode[]
  onRefresh?: () => void
}

export function WorkOrderDrawer({ equipments, symptoms, onRefresh }: WorkOrderDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { workOrderDrawerOpen, editingWorkOrder, closeWorkOrderDrawer } = useEquipmentStore()

  useEffect(() => {
    if (workOrderDrawerOpen) {
      if (editingWorkOrder) {
        form.setFieldsValue({
          equipment_id: editingWorkOrder.equipment_id,
          order_type: editingWorkOrder.order_type,
          priority: editingWorkOrder.priority,
          fault_symptom_id: editingWorkOrder.fault_symptom_id,
          fault_description: editingWorkOrder.fault_description,
        })
      } else {
        form.resetFields()
        form.setFieldsValue({ order_type: '故障维修', priority: '中' })
      }
    }
  }, [workOrderDrawerOpen, editingWorkOrder, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const data: CreateWorkOrderInput = {
        equipment_id: values.equipment_id,
        order_type: values.order_type,
        priority: values.priority,
        fault_symptom_id: values.fault_symptom_id || undefined,
        fault_description: values.fault_description || undefined,
      }
      await createWorkOrder(data)
      message.success('创建工单成功')
      closeWorkOrderDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    }
  }

  return (
    <Drawer
      title="新建维修工单"
      size={480}
      open={workOrderDrawerOpen}
      onClose={closeWorkOrderDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeWorkOrderDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>提交</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item name="equipment_id" label="关联设备" rules={[{ required: true, message: '请选择设备' }]}>
          <Select
            placeholder="选择设备"
            showSearch
            optionFilterProp="label"
            options={equipments.map((eq) => ({ label: `${eq.equipment_no} - ${eq.name}`, value: eq.id }))}
          />
        </Form.Item>
        <Form.Item name="order_type" label="工单类型" rules={[{ required: true, message: '请选择工单类型' }]}>
          <Select options={[{ label: '故障维修', value: '故障维修' }, { label: '校准', value: '校准' }]} />
        </Form.Item>
        <Form.Item name="priority" label="优先级" rules={[{ required: true, message: '请选择优先级' }]}>
          <Select options={[{ label: '紧急', value: '紧急' }, { label: '高', value: '高' }, { label: '中', value: '中' }, { label: '低', value: '低' }]} />
        </Form.Item>
        <Form.Item name="fault_symptom_id" label="故障现象">
          <Select
            placeholder="选择故障现象（可选）"
            allowClear
            showSearch
            optionFilterProp="label"
            options={symptoms.map((s) => ({ label: `${s.code} - ${s.name}`, value: s.id }))}
          />
        </Form.Item>
        <Form.Item name="fault_description" label="故障描述">
          <TextArea placeholder="请描述故障情况" rows={4} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
