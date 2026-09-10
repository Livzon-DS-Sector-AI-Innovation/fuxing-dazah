'use client'

import { Suspense } from 'react'
import { EhsChangeAcceptPage } from '@/components/safety/ehsChange'

export default function EhsChangeAcceptRoute() {
  return (
    <Suspense fallback={null}>
      <EhsChangeAcceptPage />
    </Suspense>
  )
}
