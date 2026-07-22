'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Row, Col, Popconfirm, Spin } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, FileTextOutlined } from '@ant-design/icons'
import Link from 'next/link'
import { AnnualTrainingPlan } from '@/types/hr'
import { fetchAnnualTrainingPlans } from '@/lib/api/hr'
import { deleteAnnualTrainingPlan } from '@/actions/hr'

interface AnnualPlanDeptClientProps {
  department: string
}

export default function AnnualPlanDeptClient({ department }: AnnualPlanDeptClientProps) {
  const { message } = App.useApp()
  const [plans, setPlans] = useState<AnnualTrainingPlan[]>([])
  const [loading, setLoading] = useState(true)

  const loadPlans = async () => {
    setLoading(true)
    try {
      const res = await fetchAnnualTrainingPlans({
        department,
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
  }, [department])

  const handleDelete = async (id: string) => {
    try {
      await deleteAnnualTrainingPlan(id)
      setPlans((prev) => prev.filter((p) => p.id !== id))
      message.success('删除成功')
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-[18px] font-semibold text-[var(--color-charcoal)]">
            {department}
          </h2>
          <p className="text-[14px] text-[var(--color-steel)]">
            该部门各年度培训计划
          </p>
        </div>
        <Link href="/hr/training/annual-plan/new">
          <Button type="primary" icon={<PlusOutlined />}>
            新建年度计划
          </Button>
        </Link>
      </div>

      {plans.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>{department} 暂无年度培训计划</p>
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
                      {plan.year} 年度培训计划
                    </h3>
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
    </div>
  )
}
