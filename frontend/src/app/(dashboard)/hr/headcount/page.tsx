import { Suspense } from 'react'
import HeadcountClient from '@/components/hr/HeadcountClient'
import type { HeadcountSyncInfo } from '@/components/hr/HeadcountClient'
import { fetchEmployeeSyncConfig, fetchHeadcountPlans } from '@/actions/hr'
import type { HeadcountData } from '@/types/hr'

export default async function HeadcountPage() {
  // 服务端直取：编制数据 + 同步状态（无权限/后端异常时按空态降级，不打断页面）
  let data: HeadcountData | null = null
  try {
    data = (await fetchHeadcountPlans()).data ?? null
  } catch {
    data = null
  }

  let syncInfo: HeadcountSyncInfo | null = null
  try {
    const cfg = (await fetchEmployeeSyncConfig()).data
    if (cfg) {
      syncInfo = {
        enabled: cfg.enabled,
        headcount_table_id: cfg.headcount_table_id ?? '',
        headcount_table_name: cfg.headcount_table_name ?? '',
        last_sync_at: cfg.last_sync_at,
      }
    }
  } catch {
    syncInfo = null
  }

  return (
    <Suspense fallback={<div className="h-64" />}>
      <HeadcountClient initialData={data} syncInfo={syncInfo} />
    </Suspense>
  )
}
