'use client'

// 监护补贴申报 — 独立页（2026-10-26 从特殊作业管理页迁出）。
// 数据语义：平台作业票 + 提炼四/五/六部申报台账 = 监护补贴申报数据，
// 非完整特殊作业台账（那是「全厂特殊作业一览表」，在特殊作业管理页）。

import { PageHeader } from '@/components/ui-kit'
import SubsidyPanel from '@/components/safety/SubsidyPanel'

export default function SubsidyPageClient() {
  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '监护补贴申报']}
        title="监护补贴申报"
        description="提炼四/五/六部监护补贴申报数据统计（申报作业票口径，非完整特殊作业台账）"
      />
      <SubsidyPanel />
    </div>
  )
}
