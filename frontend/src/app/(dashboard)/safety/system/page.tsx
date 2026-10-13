export const dynamic = 'force-dynamic'

import { Suspense } from 'react'

import SystemConfigPanel from '@/components/safety/system/SystemConfigPanel'

export default function SafetySystemPage() {
  // useSearchParams 的 Suspense 边界（force-dynamic 页无预渲染，此处为稳妥兜底）
  return (
    <Suspense>
      <SystemConfigPanel />
    </Suspense>
  )
}
