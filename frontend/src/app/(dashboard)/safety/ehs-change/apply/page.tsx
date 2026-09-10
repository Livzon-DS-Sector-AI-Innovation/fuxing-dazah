'use client'

import { Suspense } from 'react'
import { EhsChangeApplyPage } from '@/components/safety/ehsChange'

export default function EhsChangeApplyRoute() {
  return (
    <Suspense fallback={null}>
      <EhsChangeApplyPage />
    </Suspense>
  )
}
