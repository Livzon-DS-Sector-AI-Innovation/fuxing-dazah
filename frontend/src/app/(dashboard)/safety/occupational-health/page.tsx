// 职业健康管理（Occupational Health）— Server 壳（对标 /safety/msds/page.tsx）
//
// 只做壳：force-dynamic + Suspense；不 fetch 数据（各 Panel 用 server actions 自取数）。
// 6 Tab 全部交互在 page-client.tsx（Client Component）。

import { Suspense } from 'react'
import OccupationalHealthClient from './page-client'

export const dynamic = 'force-dynamic'

export default function OccupationalHealthPage() {
  return (
    <Suspense fallback={null}>
      <OccupationalHealthClient />
    </Suspense>
  )
}
