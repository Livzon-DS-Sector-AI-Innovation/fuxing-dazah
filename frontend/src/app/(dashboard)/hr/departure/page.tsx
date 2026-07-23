import { Suspense } from 'react'
import { DepartureClient } from '@/components/hr'

export default function DeparturePage() {
  return <Suspense fallback={<div className="h-64" />}><DepartureClient initialRecords={[]} initialTotal={0} /></Suspense>
}
