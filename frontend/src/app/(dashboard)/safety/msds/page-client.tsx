'use client'

import { Tabs } from 'antd'
import MsdsCollectionPanel from '@/components/safety/MsdsCollectionPanel'
import MsdsPanel from '@/components/safety/MsdsPanel'

export default function MsdsPageClient() {
  return (
    <Tabs
      defaultActiveKey="ledger"
      items={[
        { key: 'ledger', label: 'MSDS 台账', children: <MsdsPanel /> },
        { key: 'collection', label: '供应商资料采集', children: <MsdsCollectionPanel /> },
      ]}
      style={{ marginTop: -8 }}
    />
  )
}
