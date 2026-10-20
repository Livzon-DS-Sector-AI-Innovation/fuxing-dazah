// 设备设施管理（S8，facilities-p1）——四 Tab：三台账直读 + 校验任务

import { Suspense } from 'react'
import FacilitiesPageClient from './page-client'

export const dynamic = 'force-dynamic'

export default function FacilitiesPage() {
  return (
    <Suspense fallback={null}>
      <FacilitiesPageClient />
    </Suspense>
  )
}
