'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Row, Col, Popconfirm, Spin, Modal, Form, Select, InputNumber } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, FileTextOutlined } from '@ant-design/icons'
import Link from 'next/link'
import { AnnualTrainingPlan } from '@/types/hr'
import { fetchAnnualTrainingPlans, fetchDepartments } from '@/lib/api/hr'
import { createAnnualTrainingPlan, deleteAnnualTrainingPlan } from '@/actions/hr'

const YEAR_OPTIONS = [2024, 2025, 2026, 2027, 2028]

export default function AnnualPlanListClient() {
  const { message } = App.useApp()
  const [plans, setPlans] = useState<AnnualTrainingPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedYear, setSelectedYear] = useState<number | undefined>(2026)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [departments, setDepartments] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [modalLoading, setModalLoading] = useState(false)

  const loadPlans = async () => {
    setLoading(true)
    try {
      const res = await fetchAnnualTrainingPlans({
        year: selectedYear,
        page_size: 200 })
      setPlans(res.data || [])
    } catch (err: any) {
      message.error('加载计划列表失败: ' + (err.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPlans()
  }, [selectedYear])

  const handleDelete = async (id: string) => {
    try {
      await deleteAnnualTrainingPlan(id)
      setPlans((prev) => prev.filter((p) => p.id !== id))
      message.success('删除成功')
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const openModal = () => {
    setIsModalOpen(true)
    setModalLoading(true)
    fetchDepartments({ page_size: 200 })
      .then((res) => {
        const names = (res.data || []).map((d: any) => d.name)
        setDepartments(names)
      })
      .catch(() => {
        message.error('加载部门列表失败')
      })
      .finally(() => setModalLoading(false))
  }

  const handleCreate = async (values: { year: number; department: string }) => {
    setSubmitting(true)
    try {
      const res = await createAnnualTrainingPlan({
        year: values.year,
        department: values.department,
        status: '草稿' })
      message.success('年度培训计划创建成功')
      setIsModalOpen(false)
      form.resetFields()
      const planId = res.data?.id
      if (planId) {
        window.location.href = `/hr/training/annual-plan?id=${planId}`
      } else {
        loadPlans()
      }
    } catch (err: any) {
      const msg = err.message || ''
      if (msg.includes('已存在') || msg.includes('Duplicate')) {
        message.error('该部门年度培训计划已存在')
      } else {
        message.error(msg || '创建失败')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* 顶部筛选与新建 */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="text-sm text-[var(--color-steel)]">年份：</span>
          <Select
            style={{ width: 120 }}
            value={selectedYear}
            onChange={(val) => setSelectedYear(val)}
            options={YEAR_OPTIONS.map((y) => ({ label: `${y}年`, value: y }))}
            allowClear
            placeholder="全部年份"
          />
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openModal}>
          新建年度计划
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Spin size="large" tip="加载中..." />
        </div>
      ) : plans.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>
            {selectedYear ? `${selectedYear}年暂无年度培训计划` : '暂无年度培训计划'}
          </p>
          <p className="text-sm mt-2">点击上方按钮新建</p>
        </div>
      ) : (
        <Row gutter={[16, 16]}>
          {plans.map((plan) => (
            <Col xs={24} sm={12} lg={8} key={plan.id}>
              <Card
                hoverable
                className="h-full"
                actions={[
                  <Link key="edit" href={`/hr/training/annual-plan?id=${plan.id}`}>
                    <Button type="link" icon={<EditOutlined />}>
                      编辑
                    </Button>
                  </Link>,
                  <Popconfirm
                    key="delete"
                    title="确认删除该年度培训计划？"
                    onConfirm={() => handleDelete(plan.id)}
                  >
                    <Button type="link" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <div className="flex items-start gap-4">
                  <div className="mt-1">
                    <FileTextOutlined className="text-2xl text-[var(--color-primary)]" />
                  </div>
                  <div>
                    <h3 className="text-[16px] font-semibold text-[var(--color-charcoal)] mb-1">
                      {plan.department}
                    </h3>
                    <p className="text-[14px] text-[var(--color-steel)]">
                      {plan.year} 年度培训计划
                    </p>
                    <p className="text-[12px] text-gray-400 mt-1">
                      状态：{plan.status}
                    </p>
                  </div>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* 新建模态框 */}
      <Modal
        title="新建年度培训计划"
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false)
          form.resetFields()
        }}
        footer={null}
      >
        <Spin spinning={modalLoading} tip="加载部门列表...">
          <Form
            form={form}
            layout="vertical"
            onFinish={handleCreate}
            initialValues={{ year: new Date().getFullYear() }}
            className="mt-4"
          >
            <Form.Item
              label="年度"
              name="year"
              rules={[{ required: true, message: '请选择年度' }]}
            >
              <Select
                options={YEAR_OPTIONS.map((y) => ({ label: `${y}年`, value: y }))}
                placeholder="选择年度"
              />
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

            <Form.Item className="mb-0 flex justify-end gap-2">
              <Button onClick={() => setIsModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>
                创建
              </Button>
            </Form.Item>
          </Form>
        </Spin>
      </Modal>
    </div>
  )
}
