'use client'

import { Tabs } from 'antd'
import { PageHeader } from '@/components/ui-kit'
import FireAlarmManagement from '@/components/safety/FireAlarmManagement'
import CentralAlarmManagement from '@/components/safety/CentralAlarmManagement'
import type { CentralAlarmStats, FireAlarmStats } from '@/types/safety'

// 页级 PageHeader（双 Tab 共用）；各 Tab 内保留各自的统计行与筛选/操作区。
export default function AlarmsPageClient({
  fireStats,
  centralStats,
}: {
  fireStats: FireAlarmStats | null
  centralStats: CentralAlarmStats | null
}) {
  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', '监测报警与预警']}
        title="监测报警与预警"
        description="消防与中控报警台账、处置状态与趋势"
      />
      <Tabs
        defaultActiveKey="fire"
        items={[
          { key: 'fire', label: '消防报警', children: <FireAlarmManagement initialStats={fireStats} /> },
          { key: 'central', label: '中控报警', children: <CentralAlarmManagement initialStats={centralStats} /> },
        ]}
      />
    </div>
  )
}
