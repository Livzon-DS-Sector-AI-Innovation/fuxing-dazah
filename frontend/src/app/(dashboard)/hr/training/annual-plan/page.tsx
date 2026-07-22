'use client'

import { useSearchParams } from 'next/navigation'
import { Spin } from 'antd'
import { Suspense } from 'react'
import AnnualPlanListClient from '@/components/hr/AnnualPlanListClient'
import AnnualPlanDeptClient from '@/components/hr/AnnualPlanDeptClient'
import AnnualPlanDetailClient from '@/components/hr/AnnualPlanDetailClient'

function AnnualPlanContent() {
  const searchParams = useSearchParams()
  const planId = searchParams.get('id')
  const dept = searchParams.get('department')

  if (planId) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">年度培训计划</h1>
          <p className="text-[14px] text-[var(--color-steel)]">编辑部门年度培训计划明细</p>
        </div>
        <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
          <AnnualPlanDetailClient planId={planId} plan={null} />
        </Suspense>
      </div>
    )
  }

  if (dept) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">年度培训计划</h1>
          <p className="text-[14px] text-[var(--color-steel)]">按部门管理年度培训计划，支持新建与编辑</p>
        </div>
        <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
          <AnnualPlanDeptClient department={dept} />
        </Suspense>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">年度培训计划</h1>
        <p className="text-[14px] text-[var(--color-steel)]">按部门管理年度培训计划，支持新建与编辑</p>
      </div>
      <Suspense fallback={<div className="flex items-center justify-center py-20"><Spin size="large" /></div>}>
        <AnnualPlanListClient />
      </Suspense>
    </div>
  )
}

export default function AnnualPlanPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <AnnualPlanContent />
    </Suspense>
  )
}
