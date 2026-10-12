// 监测报警与预警 — 合并页（消防报警 + 中控报警 双 Tab）
// 取代旧 /safety/fire-alarms 与 /safety/central-alarms 两个独立页。

import { getCentralAlarmStats, getFireAlarmStats } from '@/actions/safety'
import type { CentralAlarmStats, FireAlarmStats } from '@/types/safety'
import AlarmsPageClient from './page-client'

export const dynamic = 'force-dynamic'

export default async function AlarmsPage() {
  let fireStats: FireAlarmStats | null = null
  let centralStats: CentralAlarmStats | null = null
  try {
    const [fireRes, centralRes] = await Promise.all([getFireAlarmStats(), getCentralAlarmStats()])
    if (fireRes.code === 200) fireStats = fireRes.data || null
    if (centralRes.code === 200) centralStats = centralRes.data || null
  } catch {
    /* client will refetch */
  }

  return <AlarmsPageClient fireStats={fireStats} centralStats={centralStats} />
}
