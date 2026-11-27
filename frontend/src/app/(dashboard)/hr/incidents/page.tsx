'use client'

import PageHeader from '@/components/hr/PageHeader'
import { IncidentLedger } from '@/components/hr'

export default function IncidentsPage() {
  return (
    <div className="space-y-4">
      {/* 标题与菜单名一致（菜单叫「工伤/纠纷台账」）；页头用统一 PageHeader，与其余台账页同款 */}
      <PageHeader
        title="工伤/纠纷台账"
        description="工伤与劳动纠纷记录维护（人力看板「用工风险」指标数据源），支持按类型筛选、状态跟踪（处理中/已结案）。"
      />
      <IncidentLedger />
    </div>
  )
}
