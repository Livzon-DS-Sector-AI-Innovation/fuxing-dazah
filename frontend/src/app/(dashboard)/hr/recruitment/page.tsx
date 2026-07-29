import { Suspense } from 'react'
import RecruitmentClient from '@/components/hr/RecruitmentClient'

export default function RecruitmentPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <RecruitmentClient />
    </Suspense>
  )
}
