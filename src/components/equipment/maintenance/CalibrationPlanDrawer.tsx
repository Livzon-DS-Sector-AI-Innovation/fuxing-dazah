'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, Select, InputNumber, DatePicker, Button, Space } from 'antd'
import dayjs from 'dayjs'
import { useEquipmentStore } from '@/stores/equipment'
import { createCalibrationPlan, updateCalibrationPlan } from '@/actions/equipment'
import { CreateCalibrationPlanInput, UpdateCalibrationPlanInput } from '@/types/equipment'
import { Equipment } from '@/types/equipment'

const { TextArea } = Input

interface CalibrationPlanDrawerProps {
  equipments: Equipment[]
  onRefresh?: () => void
}

export function CalibrationPlanDrawer({ equipments, onRefresh }: CalibrationPlanDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { calibrationPlanDrawerOpen, editingCalibrationPlan, closeCalibrationPlanDrawer } = useEquipmentStore()

  useEffect(() => {
    if (!calibrationPlanDrawerOpen) return
    const timer = setTimeout(() => {
      if (editingCalibrationPlan) {
        form.setFieldsValue({
          equipment_id: editingCalibrationPlan.equipment_id,
          calibration_type: editingCalibrationPlan.calibration_type,
          cycle_months: editingCalibrationPlan.cycle_months,
          last_calibration_date: editingCalibrationPlan.last_calibration_date ? dayjs(editingCalibrationPlan.last_calibration_date) : undefined,
          responsible_person_id: editingCalibrationPlan.responsible_person_id,
          remark: editingCalibrationPlan.remark,
          status: editingCalibrationPlan.status,
        })
      } else {
        form.resetFields()
        form.setFieldsValue({ calibration_type: '内部校准', cycle_months: 6 })
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [calibrationPlanDrawerOpen, editingCalibrationPlan, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingCalibrationPlan) {
        const data: UpdateCalibrationPlanInput = {
          calibration_type: values.calibration_type,
          cycle_months: values.cycle_months,
          last_calibration_date: values.last_calibration_date ? values.last_calibration_date.format('YYYY-MM-DD') : undefined,
          responsible_person_id: values.responsible_person_id || undefined,
          remark: values.remark || undefined,
          status: values.status,
        }
        await updateCalibrationPlan(editingCalibrationPlan.id, data)
        message.success('更新成功')
      } else {
        const data: CreateCalibrationPlanInput = {
          equipment_id: values.equipment_id,
          calibration_type: values.calibration_type,
          cycle_months: values.cycle_months,
          last_calibration_date: values.last_calibration_date ? values.last_calibration_date.format('YYYY-MM-DD') : undefined,
          responsible_person_id: values.responsible_person_id || undefined,
          remark: values.remark || undefined,
        }
        await createCalibrationPlan(data)
        message.success('创建成功')
      }
      closeCalibrationPlanDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    }
  }

  return (
    <Drawer
      title={editingCalibrationPlan ? '编辑校准计划' : '新增校准计划'}
      size={480}
      open={calibrationPlanDrawerOpen}
      onClose={closeCalibrationPlanDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeCalibrationPlanDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>{editingCalibrationPlan ? '保存' : '创建'}</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        {!editingCalibrationPlan && (
          <Form.Item name="equipment_id" label="关联设备" rules={[{ required: true, message: '请选择设备' }]}>
            <Select placeholder="选择设备" showSearch optionFilterProp="label"
              options={equipments.map((eq) => ({ label: `${eq.equipment_no} - ${eq.name}`, value: eq.id }))} />
          </Form.Item>
        )}
        <Form.Item name="calibration_type" label="校准类型" rules={[{ required: true, message: '请选择校准类型' }]}>
          <Select options={[{ label: '内部校准', value: '内部校准' }, { label: '外部检定', value: '外部检定' }]} />
        </Form.Item>
        <Form.Item name="cycle_months" label="校准周期（月）" rules={[{ required: true, message: '请输入校准周期' }]}>
          <InputNumber min={1} max={120} style={{ width: '100%' }} placeholder="请输入月数" />
        </Form.Item>
        <Form.Item name="last_calibration_date" label="上次校准日期">
          <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" placeholder="选择日期" />
        </Form.Item>
        <Form.Item name="responsible_person_id" label="责任人">
          <Input placeholder="责任人 ID（可选）" />
        </Form.Item>
        {editingCalibrationPlan && (
          <Form.Item name="status" label="状态">
            <Select options={[{ label: '启用', value: '启用' }, { label: '停用', value: '停用' }]} />
          </Form.Item>
        )}
        <Form.Item name="remark" label="备注">
          <TextArea placeholder="备注信息（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
