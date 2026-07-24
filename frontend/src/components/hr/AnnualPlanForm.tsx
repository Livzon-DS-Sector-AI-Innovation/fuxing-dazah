'use client'

import { useState, useEffect } from 'react'
import { App, Button, Card, Form, InputNumber, Select, Spin } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { createAnnualTrainingPlan } from '@/actions/hr'
import { fetchDepartments } from '@/lib/hr'

export default function AnnualPlanForm() {
  const { message } = App.useApp()
  const router = useRouter()
  const [form] = Form.useForm()
  const [departments, setDepartments] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchDepartments({ page_size: 200 })
      .then((res) => {
        const names = (res.data || []).map((d: any) => d.name)
        setDepartments(names)
      })
      .catch(() => {
        message.error('加载部门列表失败')
      })
      .finally(() => setLoading(false))
  }, [])

  const handleSubmit = async (values: { year: number; department: string }) => {
    setSubmitting(true)
    try {
      const res = await createAnnualTrainingPlan({
        year: values.year,
        department: values.department,
        status: '草稿' })
      message.success('年度培训计划创建成功')
      const planId = res.data?.id
      if (planId) {
        router.push(`/hr/training/annual-plan?id=${planId}`)
      } else {
        router.push('/hr/training/annual-plan')
      }
    } catch (err: any) {
      message.error(err.message || '创建失败')
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
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{ year: new Date().getFullYear() }}
      >
        <Form.Item
          label="年度"
          name="year"
          rules={[{ required: true, message: '请输入年度' }]}
        >
          <InputNumber style={{ width: '100%' }} min={2000} max={2100} />
        </Form.Item>

        <Form.Item
          label="部门"
          name="department"
          rules={[{ required: true, message: '请选择部门' }]}
        >
          <Select
            showSearch
            placeholder="选择部门"
            options={departments.map((d) => ({ label: d, value: d }))}
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Form.Item className="mb-0">
          <Button
            type="primary"
            htmlType="submit"
            icon={<SaveOutlined />}
            loading={submitting}
          >
            创建计划
          </Button>
        </Form.Item>
      </Form>
    </Card>
  )
}
