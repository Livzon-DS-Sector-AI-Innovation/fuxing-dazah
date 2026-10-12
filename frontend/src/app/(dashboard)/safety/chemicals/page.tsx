// 危化品与 MSDS 管理 — 合并页（库存 + MSDS 台账/采集 三 Tab）
// 取代旧 /safety/chemical-inventory 与 /safety/msds 两个独立页。

import { Suspense } from 'react'
import ChemicalsPageClient from './page-client'

export const dynamic = 'force-dynamic'

export default function ChemicalsPage() {
  return (
    <Suspense fallback={null}>
      <ChemicalsPageClient />
    </Suspense>
  )
}
