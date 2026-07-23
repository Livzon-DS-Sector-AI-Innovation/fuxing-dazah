import { Suspense } from 'react'
import { Spin } from 'antd'
import OnboardingApplyClient from '@/components/hr/OnboardingApplyClient'

export const dynamic = 'force-dynamic'
export const metadata = { title: '入职审批' }

export default function OnboardingApplyPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">入职审批</h1>
        <p className="text-[14px] text-[var(--color-steel)]">用人部门提交入职申请 · HR审批 · 自动创建档案</p>
      </div>
      <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
        <OnboardingApplyClient />
      </Suspense>
    </div>
  )
}
