// EHS 变更管理 —— 台账页（只读监控，3.0 口径）
// 保留台账查询/统计/AI 审核结论展示；状态机操作按钮已去除（业务在飞书多维表格与机器人）。

import { Suspense } from 'react'
import { EhsChangeLedgerPage } from '@/components/safety/ehsChange/EhsChangeLedgerPage'

export const dynamic = 'force-dynamic'

export default function EhsChangePage() {
  return (
    <Suspense fallback={null}>
      <EhsChangeLedgerPage />
    </Suspense>
  )
}
