// 危化品库存管理 — 页面（Server 壳，对标 cert-warnings/page.tsx）
// 只做壳：force-dynamic + Suspense；ChemicalInventoryPanel 用 server actions 自取数。

import { Suspense } from 'react'
import { ChemicalInventoryPanel } from '@/components/safety'

export const dynamic = 'force-dynamic'

export default function ChemicalInventoryPage() {
  return (
    <Suspense fallback={null}>
      <ChemicalInventoryPanel />
    </Suspense>
  )
}
