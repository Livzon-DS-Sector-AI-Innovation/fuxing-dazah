'use client'

import { Suspense } from 'react'
import { URSPanel } from '@/components/safety/ehsChange'

export default function URSPage() {
  return (
    <Suspense fallback={null}>
      <URSPanel />
    </Suspense>
  )
}
