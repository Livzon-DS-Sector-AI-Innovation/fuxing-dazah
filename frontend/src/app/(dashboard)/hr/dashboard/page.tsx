import { Suspense } from 'react'
import { DashboardClient } from '@/components/hr'

export const dynamic = 'force-dynamic'

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="h-96" />}>
      <DashboardClient />
    </Suspense>
  )
}
