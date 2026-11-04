'use client'

// 危化品与 MSDS 管理 — 合并页（库存 + 趋势看板 + MSDS 台账/采集 四 Tab）
// 页级 PageHeader（ui-kit）；各 Tab 内区块用 SectionCard、统计行用 StatCard（见各 Panel）。

import { Tabs } from 'antd'
import { PageHeader } from '@/components/ui-kit'
import { ChemicalInventoryPanel, ChemicalTrendPanel, MsdsPanel, MsdsCollectionPanel } from '@/components/safety'

export default function ChemicalsPageClient() {
  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '危化品与 MSDS 管理']}
        title="危化品与 MSDS 管理"
        description="危化品库存、趋势异动与安全数据说明书（MSDS）一体化查询"
      />
      <Tabs
        defaultActiveKey="inventory"
        items={[
          { key: 'inventory', label: '危化品库存', children: <ChemicalInventoryPanel /> },
          { key: 'trend', label: '趋势看板', children: <ChemicalTrendPanel /> },
          { key: 'msds', label: 'MSDS 台账', children: <MsdsPanel /> },
          { key: 'msds-collection', label: 'MSDS 供应商资料采集', children: <MsdsCollectionPanel /> },
        ]}
      />
    </div>
  )
}
