import { Suspense } from 'react'
import { DepartureClient, DepartureTabs, OffboardingBoardClient } from '@/components/hr'
import DepartureContractLedger from '@/components/hr/labor-contract/DepartureContractLedger'
import { fetchEmployeeSyncConfig } from '@/actions/hr'
import type { DepartureSyncInfo } from '@/components/hr/DepartureClient'

export const metadata = { title: '离职台账' }

export default async function DeparturePage() {
  // 同步配置服务端直取：绑定离职人员管理表后台账转只读展示；
  // 读取失败（无权限/后端异常）按未绑定处理
  let syncInfo: DepartureSyncInfo | undefined
  try {
    const cfg = (await fetchEmployeeSyncConfig()).data
    if (cfg?.departure_table_id) {
      syncInfo = {
        departure_table_name: cfg.departure_table_name || cfg.departure_table_id,
        last_sync_at: cfg.last_sync_at,
      }
    }
  } catch {
    syncInfo = undefined
  }

  return (
    <Suspense fallback={<div className="h-64" />}>
      <DepartureTabs
        ledger={<DepartureClient initialRecords={[]} initialTotal={0} syncInfo={syncInfo} />}
        board={<OffboardingBoardClient />}
        contract={<DepartureContractLedger />}
      />
    </Suspense>
  )
}
