import { Suspense } from 'react'
import { Skeleton } from 'antd'
import { MaterialsPage } from '@/components/production'

export default function MaterialsRoutePage() {
  return (
    <Suspense fallback={<Skeleton active paragraph={{ rows: 10 }} />}>
      <MaterialsPage />
    </Suspense>
  )
}
