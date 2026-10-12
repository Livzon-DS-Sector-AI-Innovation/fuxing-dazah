'use client'

import { Tabs } from 'antd'
import { ChemicalInventoryPanel, MsdsPanel, MsdsCollectionPanel } from '@/components/safety'

export default function ChemicalsPageClient() {
  return (
    <Tabs
      defaultActiveKey="inventory"
      items={[
        { key: 'inventory', label: '危化品库存', children: <ChemicalInventoryPanel /> },
        { key: 'msds', label: 'MSDS 台账', children: <MsdsPanel /> },
        { key: 'msds-collection', label: 'MSDS 供应商资料采集', children: <MsdsCollectionPanel /> },
      ]}
      style={{ marginTop: -8 }}
    />
  )
}
