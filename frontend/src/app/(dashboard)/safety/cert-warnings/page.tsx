// 人员培训及持证资质智能管理 — 持证到期预警页面（Server 壳，对标 occupational-health/page.tsx）
// 只做壳：force-dynamic + Suspense；不 fetch 数据（CertWarningPanel 用 server actions 自取数）。

import { Suspense } from 'react'
import { CertWarningPanel } from '@/components/safety'

export const dynamic = 'force-dynamic'

export default function CertWarningsPage() {
  return (
    <Suspense fallback={null}>
      <CertWarningPanel />
    </Suspense>
  )
}