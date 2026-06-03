'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, Select, DatePicker, Button, Space } from 'antd'
import dayjs from 'dayjs'
import { useEquipmentStore } from '@/stores/equipment'
import { createCalibrationRecord } from '@/actions/equipment'
import { CreateCalibrationRecordInput, CalibrationPlan } from '@/types/equipment'

const { TextArea } = Input

interface CalibrationRecordDrawerProps {
  calibrationPlans: CalibrationPlan[]
  onRefresh?: () => void
}

export function CalibrationRecordDrawer({ calibrationPlans, onRefresh }: CalibrationRecordDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const { calibrationRecordDrawerOpen, editingCalibrationRecord, closeCalibrationRecordDrawer } = useEquipmentStore()

  useEffect(() => {
    if (calibrationRecordDrawerOpen) {
      if (editingCalibrationRecord) {
        form.setFieldsValue({
          calibration_plan_id: editingCalibrationRecord.calibration_plan_id,
          calibration_type: editingCalibrationRecord.calibration_type,
          calibration_date: editingCalibrationRecord.calibration_date ? dayjs(editingCalibrationRecord.calibration_date) : undefined,
          result: editingCalibrationRecord.result,
          certificate_no: editingCalibrationRecord.certificate_no,
          calibrated_by: editingCalibrationRecord.calibrated_by,
          remark: editingCalibrationRecord.remark,
        })
      } else {
        form.resetFields()
        form.setFieldsValue({ calibration_date: dayjs(), result: '合格' })
      }
    }
  }, [calibrationRecordDrawerOpen, editingCalibrationRecord, form])

  const handlePlanChange = (planId: string) => {
    const plan = calibrationPlans.find((p) => p.id === planId)
    if (plan) form.setFieldsValue({ calibration_type: plan.calibration_type })
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const data: CreateCalibrationRecordInput = {
        calibration_plan_id: values.calibration_plan_id,
        calibration_date: values.calibration_date.format('YYYY-MM-DD'),
        calibration_type: values.calibration_type,
        result: values.result,
        certificate_no: values.certificate_no || undefined,
        calibrated_by: values.calibrated_by || undefined,
        remark: values.remark || undefined,
      }
      await createCalibrationRecord(data)
      message.success('创建校准记录成功')
      closeCalibrationRecordDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    }
  }

  return (
    <Drawer
      title="新增校准记录"
      size={480}
      open={calibrationRecordDrawerOpen}
      onClose={closeCalibrationRecordDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeCalibrationRecordDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>创建</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item name="calibration_plan_id" label="校准计划" rules={[{ required: true, message: '请选择校准计划' }]}>
          <Select
            placeholder="选择校准计划" showSearch optionFilterProp="label"
            onChange={handlePlanChange}
            options={calibrationPlans.map((plan) => ({
              label: `${plan.equipment_name || plan.equipment_id} - ${plan.calibration_type}`,
              value: plan.id,
            }))}
          />
        </Form.Item>
        <Form.Item name="calibration_date" label="校准日期" rules={[{ required: true, message: '请选择校准日期' }]}>
          <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" placeholder="选择日期" />
        </Form.Item>
        <Form.Item name="calibration_type" label="校准类型" rules={[{ required: true, message: '请选择校准类型' }]}>
          <Select options={[{ label: '内部校准', value: '内部校准' }, { label: '外部检定', value: '外部检定' }]} />
        </Form.Item>
        <Form.Item name="result" label="校准结果" rules={[{ required: true, message: '请选择校准结果' }]}>
          <Select options={[{ label: '合格', value: '合格' }, { label: '不合格', value: '不合格' }]} />
        </Form.Item>
        <Form.Item name="certificate_no" label="检定证书编号">
          <Input placeholder="证书编号（可选）" />
        </Form.Item>
        <Form.Item name="calibrated_by" label="校准单位/人员">
          <Input placeholder="校准单位或人员名称（可选）" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <TextArea placeholder="备注信息（可选）" rows={3} maxLength={500} showCount />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
