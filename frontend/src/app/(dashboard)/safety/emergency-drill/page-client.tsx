'use client'

import { Tabs } from 'antd'
import EmergencyDrillPanel from '@/components/safety/EmergencyDrillPanel'
import DrillCollectionPanel from '@/components/safety/DrillCollectionPanel'

export default function EmergencyDrillPageClient() {
  return (
    <Tabs
      defaultActiveKey="stats"
      items={[
        { key: 'stats', label: '演练计划统计', children: <EmergencyDrillPanel /> },
        { key: 'collection', label: '演练计划收录', children: <DrillCollectionPanel /> },
      ]}
      style={{ marginTop: -8 }}
    />
  )
}
