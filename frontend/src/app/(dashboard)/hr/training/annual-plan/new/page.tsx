'use client'

import { Button } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import AnnualPlanForm from '@/components/hr/AnnualPlanForm'
import PageHeader from '@/components/hr/PageHeader'

export default function NewAnnualPlanPage() {
  const router = useRouter()
  return (
    <div className="space-y-6">
      <PageHeader
        title="新建年度培训计划"
        description="选择部门并创建新的年度培训计划（厂级培训选「厂级」，所有部门可见）"
        actions={
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => router.push('/hr/training/annual-plan')}
          >
            返回计划列表
          </Button>
        }
      />

      <AnnualPlanForm />
    </div>
  )
}
