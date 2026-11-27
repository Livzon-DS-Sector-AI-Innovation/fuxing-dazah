import { Suspense } from 'react'
import CandidateDetailLoader from '@/components/hr/CandidateDetailLoader'

export default function CandidateDetailPage() {
  return (
    <div className="space-y-4">
      <Suspense fallback={<div className="h-64" />}>
        <CandidateDetailLoader />
      </Suspense>
    </div>
  )
}
