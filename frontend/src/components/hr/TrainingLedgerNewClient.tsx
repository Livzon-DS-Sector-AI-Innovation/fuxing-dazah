'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Select, Spin } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { fetchDepartments, fetchEmployees, createTrainingLedgerPage } from '@/lib/api/hr'

export default function TrainingLedgerNewClient() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [departments, setDepartments] = useState<string[]>([])
  const [employees, setEmployees] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedDept, setSelectedDept] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetchDepartments({ page_size: 200 })
      .then((res) => {
        const names = (res.data || []).map((d: any) => d.name)
        setDepartments(names)
      })
      .catch(() => message.error('加载部门列表失败'))
      .finally(() => setLoading(false))
  }, [])

  const handleDeptChange = (dept: string) => {
    setSelectedDept(dept)
    form.setFieldValue('employee_number', undefined)
    setEmployees([])
    if (!dept) return
    fetchEmployees({ department: dept, page_size: 100 })
      .then((res) => {
        setEmployees(res.data || [])
      })
      .catch(() => message.error('加载人员列表失败'))
  }

  const handleSubmit = async (values: { employee_number: string }) => {
    const emp = employees.find((e) => e.employee_number === values.employee_number)
    if (!emp) {
      message.error('请选择人员')
      return
    }
    setSubmitting(true)
    try {
      await createTrainingLedgerPage({
        employee_number: emp.employee_number,
        employee_name: emp.name })
      message.success('培训台账创建成功')
      window.location.href = `/hr/training/ledger?employee_number=${emp.employee_number}`
    } catch (err: any) {
      if (err.message?.includes('Duplicate') || err.message?.includes('已存在')) {
        message.warning('该员工的培训台账已存在')
        window.location.href = `/hr/training/ledger?employee_number=${emp.employee_number}`
      } else {
        message.error(err.message || '创建失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spin size="large" description="加载中..." />
      </div>
    )
  }

  return (
    <Card className="max-w-xl">
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        <Form.Item
          label="所属部门"
          name="department"
          rules={[{ required: true, message: '请选择部门' }]}
        >
          <Select
            showSearch
            placeholder="选择部门"
            options={departments.map((d) => ({ label: d, value: d }))}
            onChange={handleDeptChange}
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Form.Item
          label="人员"
          name="employee_number"
          rules={[{ required: true, message: '请选择人员' }]}
        >
          <Select
            showSearch
            placeholder={selectedDept ? '选择人员' : '请先选择部门'}
            disabled={!selectedDept}
            options={employees.map((e) => ({
              label: `${e.name} (${e.employee_number})`,
              value: e.employee_number }))}
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Form.Item className="mb-0">
          <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={submitting}>
            创建培训台账
          </Button>
        </Form.Item>
      </Form>
    </Card>
  )
}
