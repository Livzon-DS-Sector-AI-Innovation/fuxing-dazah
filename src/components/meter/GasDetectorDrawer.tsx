'use client'

import { useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, DatePicker, Space, Button } from 'antd'
import { GasDetectorRecord, GasDetectorCreate, GasDetectorUpdate } from '@/types/meter'
import { createGasDetector, updateGasDetector } from '@/actions/meter'
import { DepartmentSelect } from './DepartmentSelect'
import dayjs from 'dayjs'

interface Props {
  open: boolean
  record: GasDetectorRecord | null
  onClose: () => void
}

export function GasDetectorDrawer({ open, record, onClose }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const isEdit = !!record

  useEffect(() => {
    if (open) {
      if (record) {
        form.setFieldsValue({
          instrument_name: record.instrument_name,
          detection_model: record.detection_model,
          measurement_range: record.measurement_range,
          product_number: record.product_number,
          installation_type: record.installation_type,
          installation_location: record.installation_location,
          medium: record.medium,
          calibration_factor: record.calibration_factor,
          manufacturer_supplier: record.manufacturer_supplier,
          manufacturer: record.manufacturer,
          department: record.department,
          detection_unit: record.detection_unit,
          calibration_result: record.calibration_result,
          calibration_date: record.calibration_date ? dayjs(record.calibration_date) : null,
          next_calibration_date: record.next_calibration_date ? dayjs(record.next_calibration_date) : null,
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
      const data: GasDetectorCreate | GasDetectorUpdate = {
        ...values,
        calibration_date: values.calibration_date?.format('YYYY-MM-DD') ?? null,
        next_calibration_date: values.next_calibration_date?.format('YYYY-MM-DD') ?? null,
      }
      if (isEdit) {
        await updateGasDetector(record!.id, data as GasDetectorUpdate)
        message.success('更新成功')
      } else {
        await createGasDetector(data as GasDetectorCreate)
        message.success('创建成功')
      }
      onClose()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Drawer
      title={isEdit ? '编辑探测器' : '新增探测器'}
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
      <Form form={form} layout="vertical">
        <Form.Item name="instrument_name" label="器具名称" rules={[{ required: true, message: '请输入器具名称' }]}>
          <Input placeholder="如：氧气检测仪(O2)" />
        </Form.Item>

        <Form.Item name="detection_model" label="检测型号">
          <Input placeholder="如：YT-95H-02-A" />
        </Form.Item>

        <Form.Item name="measurement_range" label="量程">
          <Input placeholder="如：0~30%VOL" />
        </Form.Item>

        <Form.Item name="product_number" label="产品编号">
          <Input placeholder="产品编号" />
        </Form.Item>

        <Form.Item name="installation_type" label="安装方式">
          <Select
            options={[
              { label: '固定式', value: '固定式' },
              { label: '便携式', value: '便携式' },
            ]}
          />
        </Form.Item>

        <Form.Item name="installation_location" label="安装位置">
          <Input placeholder="安装位置" />
        </Form.Item>

        <Form.Item name="medium" label="使用介质">
          <Input placeholder="如：氮气" />
        </Form.Item>

        <Form.Item name="calibration_factor" label="标定系数">
          <Input placeholder="如：空气1:1" />
        </Form.Item>

        <Form.Item name="manufacturer_supplier" label="传感器出厂日期">
          <Input placeholder="制造商" />
        </Form.Item>

        <Form.Item name="manufacturer" label="制造单位">
          <Input placeholder="制造单位" />
        </Form.Item>

        <Form.Item name="department" label="部门">
          <DepartmentSelect source="gas_detector" />
        </Form.Item>

        <Form.Item name="detection_unit" label="检测单位">
          <Input placeholder="检测单位" />
        </Form.Item>

        <Form.Item name="calibration_result" label="检定结论">
          <Input placeholder="检定结论" />
        </Form.Item>

        <Form.Item name="calibration_date" label="检定时间">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="next_calibration_date" label="下次检定时间">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} placeholder="备注信息" maxLength={500} />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
