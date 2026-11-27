import { Suspense } from 'react'
import { Skeleton } from 'antd'
import { DepartureWorkspace } from '@/components/hr'
import { fetchEmployeeSyncConfig } from '@/actions/hr'
import type { DepartureSyncInfo } from '@/components/hr/DepartureClient'

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
    // 外壳要读网址参数（?case= 深链），必须包在 Suspense 里；加载期间给骨架屏而不是空白
    <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} title={false} />}>
      <DepartureWorkspace syncInfo={syncInfo} />
    </Suspense>
  )
}
