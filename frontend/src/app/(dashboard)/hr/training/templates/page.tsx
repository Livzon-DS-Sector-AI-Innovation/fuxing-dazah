import { Suspense } from 'react'
import TrainingTemplatesClient from '@/components/hr/TrainingTemplatesClient'

export default function TrainingTemplatesPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <TrainingTemplatesClient />
    </Suspense>
  )
}
