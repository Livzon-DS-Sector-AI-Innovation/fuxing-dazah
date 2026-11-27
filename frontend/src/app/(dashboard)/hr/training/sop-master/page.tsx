import { Suspense } from 'react'
import SopMasterClient from '@/components/hr/sop-training/SopMasterClient'

export default function SopMasterPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <SopMasterClient />
    </Suspense>
  )
}
