import { Suspense } from 'react'
import SopEntryClient from '@/components/hr/sop-training/SopEntryClient'

export default function SopSecondaryPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <SopEntryClient />
    </Suspense>
  )
}
