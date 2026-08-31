'use client'

import { Button } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import AnnualPlanForm from '@/components/hr/AnnualPlanForm'

export default function NewAnnualPlanPage() {
  const router = useRouter()
  return (
    <div className="space-y-6">
      <div>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          className="mb-2 pl-0"
          onClick={() => router.push('/hr/training/annual-plan')}
        >
          返回计划列表
        </Button>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          新建年度培训计划
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          选择部门并创建新的年度培训计划（厂级培训选「厂级」，所有部门可见）
        </p>
      </div>

      <AnnualPlanForm />
    </div>
  )
}
