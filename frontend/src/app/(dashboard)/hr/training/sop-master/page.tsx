import { Suspense } from 'react'
import SopMasterClient from '@/components/hr/sop-training/SopMasterClient'

export const metadata = { title: 'SOP培训登记表' }

export default function SopMasterPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <SopMasterClient />
    </Suspense>
  )
}
