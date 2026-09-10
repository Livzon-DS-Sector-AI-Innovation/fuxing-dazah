import FireAlarmManagement from '@/components/safety/FireAlarmManagement'
import { getFireAlarmStats } from '@/actions/safety'
import type { FireAlarmStats } from '@/types/safety'

export const dynamic = 'force-dynamic'

export default async function FireAlarmsPage() {
  let initialStats: FireAlarmStats | null = null
  try {
    const res = await getFireAlarmStats()
    if (res.code === 200) initialStats = res.data || null
  } catch { /* client will refetch */ }

  return <FireAlarmManagement initialStats={initialStats} />
}
