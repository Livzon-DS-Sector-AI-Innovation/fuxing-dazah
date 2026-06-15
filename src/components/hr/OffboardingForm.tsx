'use client'

import { useEffect, useState } from 'react'
import { App, Modal, Form, Select, DatePicker, Input } from 'antd'
import dayjs from 'dayjs'
import { Employee, OffboardingRecord, OffboardingRecordCreateInput, OffboardingRecordUpdateInput } from '@/types/hr'
import { createOffboardingRecord, updateOffboardingRecord } from '@/actions/hr'
import { fetchEmployees } from '@/lib/api/hr'

interface OffboardingFormProps {
  open: boolean
  record: OffboardingRecord | null
  onClose: () => void
  onSuccess: () => void
}

export default function OffboardingForm({ open, record, onClose, onSuccess }: OffboardingFormProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const isEdit = !!record
  const [employees, setEmployees] = useState<Employee[]>([])

  useEffect(() => {
    if (open) {
      // 加载在职员工列表
      fetchEmployees({ status: '在职', page_size: 100 })
        .then((res) => setEmployees(res.data))
        .catch(() => setEmployees([]))

      if (record) {
        form.setFieldsValue({
          ...record,
          offboarding_date: record.offboarding_date ? dayjs(record.offboarding_date) : null })
      } else {
        form.resetFields()
        form.setFieldsValue({ offboarding_type: '辞职', handover_status: '待交接' })
      }
    }
  }, [open, record, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const payload = {
        ...values,
        offboarding_date: values.offboarding_date ? values.offboarding_date.format('YYYY-MM-DD') : undefined }

      if (isEdit && record) {
        await updateOffboardingRecord(record.id, payload as OffboardingRecordUpdateInput)
        message.success('离职记录更新成功')
      } else {
        await createOffboardingRecord(payload as OffboardingRecordCreateInput)
        message.success('离职记录创建成功')
      }

      form.resetFields()
      onSuccess()
      onClose()
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  const employeeOptions = employees.map((e) => ({
    value: e.id,
    label: `${e.name} (${e.employee_number})` }))

  return (
    <Modal
      title={isEdit ? '编辑离职记录' : '新增离职记录'}
      open={open}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      width={560}
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="employee_id"
          label="员工"
          rules={[{ required: true, message: '请选择员工' }]}
        >
          <Select
            placeholder="请选择员工"
            options={employeeOptions}
            showSearch
            disabled={isEdit}
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <div className="grid grid-cols-2 gap-4">
          <Form.Item
            name="offboarding_date"
            label="离职日期"
            rules={[{ required: true, message: '请选择离职日期' }]}
          >
            <DatePicker className="w-full" placeholder="请选择离职日期" />
          </Form.Item>

          <Form.Item
            name="offboarding_type"
            label="离职类型"
            rules={[{ required: true, message: '请选择离职类型' }]}
          >
            <Select
              placeholder="请选择离职类型"
              options={[
                { value: '辞职', label: '辞职' },
                { value: '辞退', label: '辞退' },
                { value: '合同到期', label: '合同到期' },
                { value: '退休', label: '退休' },
                { value: '其他', label: '其他' },
              ]}
            />
          </Form.Item>
        </div>

        <Form.Item
          name="reason"
          label="离职原因"
        >
          <Input.TextArea rows={2} placeholder="请输入离职原因" />
        </Form.Item>

        <div className="grid grid-cols-2 gap-4">
          <Form.Item
            name="handover_status"
            label="交接状态"
            rules={[{ required: true, message: '请选择交接状态' }]}
          >
            <Select
              placeholder="请选择交接状态"
              options={[
                { value: '待交接', label: '待交接' },
                { value: '交接中', label: '交接中' },
                { value: '已完成', label: '已完成' },
              ]}
            />
          </Form.Item>
        </div>

        <Form.Item
          name="notes"
          label="备注"
        >
          <Input.TextArea rows={2} placeholder="请输入备注" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
