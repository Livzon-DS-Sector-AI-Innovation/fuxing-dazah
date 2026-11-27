import { Suspense } from 'react'
import { SopCatalogManager } from '@/components/hr/sop-catalog'

export const metadata = { title: 'SOP目录' }

export default function SopCatalogPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <SopCatalogManager />
    </Suspense>
  )
}
