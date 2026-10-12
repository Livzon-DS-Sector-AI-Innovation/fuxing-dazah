import { Suspense } from 'react'
import type { Metadata } from 'next'
import { SafetyOverviewDashboard } from '@/components/safety/SafetyOverviewDashboard'

export const metadata: Metadata = {
  title: '安全总览驾驶舱',
  description: '今日安全态势只读总览——隐患 / 作业 / 报警 / 证书 / 危化品 / 速递（3.0 只读监控）',
}

export default function SafetyPage() {
  return (
    <Suspense>
      <SafetyOverviewDashboard />
    </Suspense>
  )
}
