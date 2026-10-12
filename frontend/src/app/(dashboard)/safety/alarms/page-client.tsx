'use client'

import { Tabs } from 'antd'
import FireAlarmManagement from '@/components/safety/FireAlarmManagement'
import CentralAlarmManagement from '@/components/safety/CentralAlarmManagement'
import type { CentralAlarmStats, FireAlarmStats } from '@/types/safety'

export default function AlarmsPageClient({
  fireStats,
  centralStats,
}: {
  fireStats: FireAlarmStats | null
  centralStats: CentralAlarmStats | null
}) {
  return (
    <Tabs
      defaultActiveKey="fire"
      items={[
        { key: 'fire', label: '消防报警', children: <FireAlarmManagement initialStats={fireStats} /> },
        { key: 'central', label: '中控报警', children: <CentralAlarmManagement initialStats={centralStats} /> },
      ]}
      style={{ marginTop: -8 }}
    />
  )
}
