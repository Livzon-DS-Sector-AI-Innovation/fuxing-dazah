import { Suspense } from 'react'
import EmployeeInfoCollectionPanel from '@/components/hr/EmployeeInfoCollectionPanel'
import ProbationPanel from '@/components/hr/ProbationPanel'
import EmployeeProfileClient from '@/components/hr/EmployeeProfileClient'
import EmployeeSyncSettings from '@/components/hr/EmployeeSyncSettings'
import { fetchEmployeeSyncConfig } from '@/actions/hr'
import type { EmployeeSyncBanner, EmployeeSyncConfig } from '@/types/hr'

export default async function EmployeeProfilePage({
  searchParams,
}: {
  searchParams: Promise<{ department?: string }>
}) {
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

  // ?department=xxx：编制页等部门下钻进入时预选部门页签
  const { department } = await searchParams

  return (
    <Suspense fallback={<div className="h-64" />}>
      <div className="space-y-4">
        {/* 面板入口按钮经 headerActions 并入标题行，不再单独占一行 */}
        <EmployeeProfileClient
          initialEmployees={[]}
          initialTotal={0}
          syncInfo={syncInfo}
          initialDepartment={department}
          headerActions={
            <>
              <EmployeeInfoCollectionPanel />
              <ProbationPanel />
            </>
          }
        />
        {/* 同步配置属管理设置：收在页尾，不抢占列表阅读区 */}
        <EmployeeSyncSettings initialConfig={syncConfig} />
      </div>
    </Suspense>
  )
}
