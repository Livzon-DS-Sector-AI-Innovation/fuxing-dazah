'use client'

// R3 运维自愈观测页 —— SuperAgent R3 二期（工单列表 + 时间线回放 + retry/一键执行）。

import { PageHeader } from '@/components/ui-kit'
import OpsSelfhealPanel from '@/components/safety/OpsSelfhealPanel'

export default function OpsSelfhealPageClient() {
  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '运维自愈']}
        title="运维自愈工单"
        description="SuperAgent R3 告警自修复观测：故障信号自动开单诊断 → 授权内修复 → 恢复双确认关单；任一工单可回放完整时间线"
      />
      <OpsSelfhealPanel />
    </div>
  )
}
