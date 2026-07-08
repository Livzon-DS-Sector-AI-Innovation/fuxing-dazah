'use client'

import { useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, DatePicker, Space, Button } from 'antd'
import { InstrumentRecord, InstrumentCreate, InstrumentUpdate } from '@/types/meter'
import { createInstrument, updateInstrument } from '@/actions/meter'
import { DepartmentSelect } from './DepartmentSelect'
import dayjs from 'dayjs'

interface Props {
  open: boolean
  record: InstrumentRecord | null
  onClose: () => void
}

export function InstrumentDrawer({ open, record, onClose }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const isEdit = !!record

  useEffect(() => {
    if (open) {
      if (record) {
        form.setFieldsValue({
          asset_number: record.asset_number,
          instrument_name: record.instrument_name,
          model_spec: record.model_spec,
          measurement_range: record.measurement_range,
          accuracy_grade: record.accuracy_grade,
          serial_number: record.serial_number,
          calibration_cycle_months: record.calibration_cycle_months,
          location: record.location,
          manufacturer: record.manufacturer,
          department: record.department,
          status: record.status,
          color_marking: record.color_marking,
          calibration_date: record.calibration_date ? dayjs(record.calibration_date) : null,
          next_calibration_date: record.next_calibration_date ? dayjs(record.next_calibration_date) : null,
          calibration_unit: record.calibration_unit,
          calibration_result: record.calibration_result,
        })
      } else {
        form.resetFields()
      }
    }
  }, [open, record, form])

  async function handleSubmit() {
    try {
      const values = await form.validateFields()
      setLoading(true)
      const data: InstrumentCreate | InstrumentUpdate = {
        ...values,
        calibration_date: values.calibration_date?.format('YYYY-MM-DD') ?? null,
        next_calibration_date: values.next_calibration_date?.format('YYYY-MM-DD') ?? null,
      }
      if (isEdit) {
        await updateInstrument(record!.id, data as InstrumentUpdate)
        message.success('更新成功')
      } else {
        await createInstrument(data as InstrumentCreate)
        message.success('创建成功')
      }
      onClose()
    } catch (e: any) {
      if (e?.errorFields) return // form validation
      message.error(e?.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  const statusOptions = [
    { label: '在用', value: '在用' },
    { label: '停用', value: '停用' },
  ]

  return (
    <Drawer
      title={isEdit ? '编辑计量器具' : '新增计量器具'}
      open={open}
      onClose={onClose}
      size="large"
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={loading} onClick={handleSubmit}>
            {isEdit ? '保存' : '创建'}
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" initialValues={{ status: '在用', calibration_cycle_months: 12 }}>
        <Form.Item name="asset_number" label="资产编号" rules={[{ required: true, message: '请输入资产编号' }]}>
          <Input placeholder="资产编号" />
        </Form.Item>

        <Form.Item name="instrument_name" label="器具名称" rules={[{ required: true, message: '请输入器具名称' }]}>
          <Input placeholder="如：工作压力表" />
        </Form.Item>

        <Form.Item name="model_spec" label="型号规格">
          <Input placeholder="如：Y-60" />
        </Form.Item>

        <Form.Item name="measurement_range" label="测量范围">
          <Input placeholder="如：0-60MPa" />
        </Form.Item>

        <Form.Item name="accuracy_grade" label="精度等级">
          <Input placeholder="如：2.5" />
        </Form.Item>

        <Form.Item name="serial_number" label="出厂编号">
          <Input placeholder="出厂编号" />
        </Form.Item>

        <Form.Item name="calibration_cycle_months" label="检定周期(月)">
          <Select
            options={[6, 12, 24, 36].map((v) => ({ label: `${v} 个月`, value: v }))}
          />
        </Form.Item>

        <Form.Item name="location" label="使用地点">
          <Input placeholder="使用地点" />
        </Form.Item>

        <Form.Item name="manufacturer" label="制造商">
          <Input placeholder="制造商" />
        </Form.Item>

        <Form.Item name="department" label="部门">
          <DepartmentSelect source="instrument" />
        </Form.Item>

        <Form.Item name="status" label="状态">
          <Select options={statusOptions} />
        </Form.Item>

        <Form.Item name="color_marking" label="彩色标志">
          <Input placeholder="如：合格B" />
        </Form.Item>

        <Form.Item name="calibration_date" label="检定日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="calibration_unit" label="检定单位">
          <Input placeholder="检定单位" />
        </Form.Item>

        <Form.Item name="calibration_result" label="检定结论">
          <Input placeholder="检定结论" />
        </Form.Item>

        <Form.Item name="next_calibration_date" label="下次检定日期">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} placeholder="备注信息" maxLength={500} />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
