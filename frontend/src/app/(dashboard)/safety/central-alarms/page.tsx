import CentralAlarmManagement from '@/components/safety/CentralAlarmManagement'
import { getCentralAlarmStats } from '@/actions/safety'
import type { CentralAlarmStats } from '@/types/safety'

export const dynamic = 'force-dynamic'

export default async function CentralAlarmsPage() {
  let initialStats: CentralAlarmStats | null = null
  try {
    const res = await getCentralAlarmStats()
    if (res.code === 200) initialStats = res.data || null
  } catch { /* client will refetch */ }

  return <CentralAlarmManagement initialStats={initialStats} />
}
