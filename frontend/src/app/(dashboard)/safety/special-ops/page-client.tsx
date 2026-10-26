'use client'

// 特殊作业管理 — 合并页（特殊作业台账 + 监护补贴 两 Tab）
// 页级 PageHeader（ui-kit）；Tab1 为既有台账组件（内部页头已上提至此）。

import { Tabs } from 'antd'
import { PageHeader } from '@/components/ui-kit'
import SpecialOpsManagement from '@/components/safety/SpecialOpsManagement'
import SubsidyPanel from '@/components/safety/SubsidyPanel'
import type { SpecialOperationLedgerStats } from '@/types/safety'

export default function SpecialOpsPageClient({
  initialStats,
}: {
  initialStats: SpecialOperationLedgerStats[]
}) {
  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '特殊作业管理']}
        title="特殊作业管理"
        description="八类特殊作业票台账、当日作业态势与监护补贴统计"
      />
      <Tabs
        defaultActiveKey="ledger"
        items={[
          {
            key: 'ledger',
            label: '特殊作业台账',
            children: <SpecialOpsManagement initialStats={initialStats} />,
          },
          {
            key: 'subsidy',
            label: '监护补贴',
            children: <SubsidyPanel />,
          },
        ]}
      />
    </div>
  )
}
