import PageHeader from '@/components/hr/PageHeader'
import { Suspense } from 'react'
import { Spin } from 'antd'
import TrainingLedgerNewClient from '@/components/hr/TrainingLedgerNewClient'

export default function TrainingLedgerNewPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="新建培训台账" description="选择部门与人员后创建个人培训台账" />

      <Suspense
        fallback={
          <div className="flex items-center justify-center py-20">
            <Spin size="large" tip="加载中..." />
          </div>
        }
      >
        <TrainingLedgerNewClient />
      </Suspense>
    </div>
  )
}
