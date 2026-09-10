import { Suspense } from 'react'
import EmergencyDrillPageClient from './page-client'

export const dynamic = 'force-dynamic'

export default function EmergencyDrillPage() {
  return (
    <Suspense fallback={null}>
      <EmergencyDrillPageClient />
    </Suspense>
  )
}
