import { Suspense } from 'react'
import { Skeleton } from 'antd'
import { IntermediateTypesPage } from '@/components/production/process/IntermediateTypesPage'

export default function IntermediateTypesRoutePage() {
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 10 }} />}>
      <IntermediateTypesPage />
    </Suspense>
  )
}
