import { Suspense } from 'react'
import TrainingTemplatesClient from '@/components/hr/TrainingTemplatesClient'

export const metadata = { title: '导出模板' }

export default function TrainingTemplatesPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <TrainingTemplatesClient />
    </Suspense>
  )
}
