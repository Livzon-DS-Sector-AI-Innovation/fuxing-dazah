'use client'

import { useEffect, useMemo, useState } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space } from 'antd'
import { useEquipmentStore } from '@/stores/equipment'
import { createWorkOrder, updateWorkOrder } from '@/actions/equipment'
import { CreateWorkOrderInput, UpdateWorkOrderInput, FailureCode, WorkOrderStatus, Maintainer } from '@/types/equipment'
import { Equipment } from '@/types/equipment'
import { fetchAllUsersClient } from '@/lib/api/equipment-client'

const { TextArea } = Input

const statusOptions: { label: string; value: WorkOrderStatus }[] = [
  { label: '待处理', value: '待处理' },
  { label: '执行中', value: '执行中' },
  { label: '待验收', value: '待验收' },
  { label: '已完成', value: '已完成' },
  { label: '已关闭', value: '已关闭' },
]

interface WorkOrderDrawerProps {
  equipments: Equipment[]
  symptoms: FailureCode[]
  onRefresh?: () => void
}

export function WorkOrderDrawer({ equipments, symptoms, onRefresh }: WorkOrderDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { workOrderDrawerOpen, editingWorkOrder, closeWorkOrderDrawer } = useEquipmentStore()
  const [maintainers, setMaintainers] = useState<Maintainer[]>([])

  const isEditing = !!editingWorkOrder

  useEffect(() => {
    if (workOrderDrawerOpen) {
      fetchAllUsersClient().then((list) => {
        setMaintainers(list)
        // 加载完后重新设置责任人，让 Select 能匹配选项显示姓名
        if (editingWorkOrder?.responsible_person_id) {
          form.setFieldsValue({ responsible_person_id: editingWorkOrder.responsible_person_id })
        }
      }).catch(() => {})
    }
  }, [workOrderDrawerOpen])

  // 构建 initialValues：编辑时填充已有数据，新建时给默认值
  const initialValues = useMemo(() => {
    if (editingWorkOrder) {
      return {
        equipment_id: editingWorkOrder.equipment_id,
        order_type: editingWorkOrder.order_type,
        priority: editingWorkOrder.priority,
        status: editingWorkOrder.status,
        fault_symptom_id: editingWorkOrder.fault_symptom_id ?? undefined,
        fault_description: editingWorkOrder.fault_description ?? undefined,
        responsible_person_id: editingWorkOrder.responsible_person_id ?? undefined,
      }
    }
    return { order_type: '故障维修', priority: '中' }
  }, [editingWorkOrder])

  // 每次打开/关闭时重置表单
  useEffect(() => {
    if (workOrderDrawerOpen) {
      form.setFieldsValue(initialValues)
    }
  }, [workOrderDrawerOpen, initialValues])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (isEditing && editingWorkOrder) {
        const data: UpdateWorkOrderInput = {
          equipment_id: values.equipment_id,
          order_type: values.order_type,
          priority: values.priority,
          status: values.status,
          fault_symptom_id: values.fault_symptom_id || undefined,
          fault_description: values.fault_description || undefined,
          responsible_person_id: values.responsible_person_id || undefined,
        }
        await updateWorkOrder(editingWorkOrder.id, data)
        message.success('更新工单成功')
      } else {
        const data: CreateWorkOrderInput = {
          equipment_id: values.equipment_id,
          order_type: values.order_type,
          priority: values.priority,
          fault_symptom_id: values.fault_symptom_id || undefined,
          fault_description: values.fault_description || undefined,
          responsible_person_id: values.responsible_person_id || undefined,
        }
        await createWorkOrder(data)
        message.success('创建工单成功')
      }
      closeWorkOrderDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.errorFields) return
      if (error?.message) message.error(error.message)
    }
  }

  return (
    <Drawer
      title={isEditing ? '编辑维修工单' : '新建维修工单'}
      size={480}
      open={workOrderDrawerOpen}
      onClose={closeWorkOrderDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeWorkOrderDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>{isEditing ? '保存' : '提交'}</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional">
        <Form.Item name="equipment_id" label="关联设备" rules={[{ required: true, message: '请选择设备' }]}>
          <Select
            placeholder="选择设备"
            showSearch
            optionFilterProp="label"
            options={equipments.map((eq) => ({ label: `${eq.equipment_no} - ${eq.name}`, value: eq.id }))}
            onChange={(eqId: string) => {
              // 新建模式：自动填入设备责任人
              if (!isEditing) {
                const eq = equipments.find(e => e.id === eqId)
                form.setFieldsValue({
                  responsible_person_id: eq?.responsible_person_id || undefined,
                })
              }
            }}
          />
        </Form.Item>
        <Form.Item name="order_type" label="工单类型" rules={[{ required: true, message: '请选择工单类型' }]}>
          <Select options={[
            { label: '故障维修', value: '故障维修' },
            { label: '计划维护', value: '计划维护' },
            { label: '校准', value: '校准' },
            { label: '异常处理', value: '异常处理' },
            { label: '日常维护', value: '日常维护' },
          ]} />
        </Form.Item>
        <Form.Item name="priority" label="优先级" rules={[{ required: true, message: '请选择优先级' }]}>
          <Select options={[{ label: '紧急', value: '紧急' }, { label: '高', value: '高' }, { label: '中', value: '中' }, { label: '低', value: '低' }]} />
        </Form.Item>
        <Form.Item name="responsible_person_id" label="责任人" rules={[{ required: true, message: '请选择责任人' }]}>
          <Select
            placeholder="选择责任人"
            showSearch
            optionFilterProp="label"
            options={maintainers.map((m) => ({
              label: `${m.name} (${m.employee_no || '-'})`,
              value: m.user_id,
            }))}
          />
        </Form.Item>
        {isEditing && (
          <Form.Item name="status" label="工单状态" rules={[{ required: true, message: '请选择工单状态' }]}>
            <Select options={statusOptions} />
          </Form.Item>
        )}
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
