import { Suspense } from 'react'
import SopEntryClient from '@/components/hr/SopEntryClient'

export default function SopSecondaryPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <SopEntryClient />
    </Suspense>
  )
}
