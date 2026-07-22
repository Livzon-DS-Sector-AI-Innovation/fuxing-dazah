import SpecialOpsManagement from '@/components/safety/SpecialOpsManagement'
import { getSpecialOperationLedgerStats } from '@/actions/safety'
import type { SpecialOperationLedgerStats } from '@/types/safety'

export const dynamic = 'force-dynamic'

export default async function SpecialOpsPage() {
  let initialStats: SpecialOperationLedgerStats[] = []
  try {
    const res = await getSpecialOperationLedgerStats()
    if (res.code === 200) initialStats = res.data || []
  } catch { /* client will refetch */ }

  return <SpecialOpsManagement initialStats={initialStats} />
}
