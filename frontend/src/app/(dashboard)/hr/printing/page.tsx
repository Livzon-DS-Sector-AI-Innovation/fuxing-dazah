import { Suspense } from 'react'
import { PrintingClient } from '@/components/hr'

export default function PrintingPage() {
  return <Suspense fallback={<div className="h-64" />}><PrintingClient initialDepartments={[]} /></Suspense>
}
