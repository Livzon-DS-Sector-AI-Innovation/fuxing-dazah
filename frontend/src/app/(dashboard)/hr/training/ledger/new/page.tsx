import { Suspense } from 'react'
import { Spin } from 'antd'
import TrainingLedgerNewClient from '@/components/hr/TrainingLedgerNewClient'

export default function TrainingLedgerNewPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          新建培训台账
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          选择部门与人员后创建个人培训台账
        </p>
      </div>

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
