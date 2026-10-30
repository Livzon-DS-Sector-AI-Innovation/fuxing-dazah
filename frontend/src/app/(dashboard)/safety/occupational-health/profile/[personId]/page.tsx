// 职业健康个人完整档案 — Server 壳（对标 ../page.tsx）
//
// 只做壳：force-dynamic + Suspense；数据在 page-client.tsx 自取。
// 路由 /safety/occupational-health/profile/[personId]（人员台账「查看档案」进入）。

import { Suspense } from 'react'
import OccupationalHealthProfileClient from './page-client'

export const dynamic = 'force-dynamic'

export default async function OccupationalHealthProfilePage({
  params,
}: {
  params: Promise<{ personId: string }>
}) {
  const { personId } = await params
  return (
    <Suspense fallback={null}>
      <OccupationalHealthProfileClient personId={decodeURIComponent(personId)} />
    </Suspense>
  )
}
