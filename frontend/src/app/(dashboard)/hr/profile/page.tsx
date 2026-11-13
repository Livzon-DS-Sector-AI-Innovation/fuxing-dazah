import { Suspense } from 'react'
import EmployeeInfoCollectionPanel from '@/components/hr/EmployeeInfoCollectionPanel'
import ProbationPanel from '@/components/hr/ProbationPanel'
import EmployeeProfileClient from '@/components/hr/EmployeeProfileClient'
import EmployeeSyncSettings from '@/components/hr/EmployeeSyncSettings'
import { fetchEmployeeSyncConfig } from '@/actions/hr'
import type { EmployeeSyncBanner, EmployeeSyncConfig } from '@/types/hr'

export default async function EmployeeProfilePage() {
  // 同步配置服务端直取：档案页 banner + 同步管理折叠面板共用；
  // 读取失败（无权限/后端异常）按未启用处理
  let syncConfig: EmployeeSyncConfig | null = null
  try {
    syncConfig = (await fetchEmployeeSyncConfig()).data ?? null
  } catch {
    syncConfig = null
  }

  let syncInfo: EmployeeSyncBanner | undefined
  if (syncConfig?.enabled && syncConfig.app_token) {
    syncInfo = {
      app_token: syncConfig.app_token,
      source_table_id: syncConfig.source_table_id,
      last_sync_at: syncConfig.last_sync_at,
    }
  }

  return (
    <Suspense fallback={<div className="h-64" />}>
      <div className="space-y-4">
        <div className="flex justify-end gap-2 -mb-2">
          <EmployeeInfoCollectionPanel />
          <ProbationPanel />
        </div>
        <EmployeeSyncSettings initialConfig={syncConfig} />
        <EmployeeProfileClient
          initialEmployees={[]}
          initialTotal={0}
          syncInfo={syncInfo}
        />
      </div>
    </Suspense>
  )
}
