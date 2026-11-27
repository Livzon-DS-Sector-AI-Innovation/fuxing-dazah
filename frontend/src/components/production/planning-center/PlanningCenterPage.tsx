'use client'

import { Suspense } from 'react'
import { App, ConfigProvider, Tabs } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useSearchParams, useRouter } from 'next/navigation'
import { antdTheme } from '@/lib/antd-theme'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { PageGuideButton } from '../shared/PageGuideButton'
import { DemandPool } from './DemandPool'
import { PlanOrderList } from './PlanOrderList'
import { ScheduleView } from './ScheduleView'
import { PageHeading } from '@/components/shared/PageHeading'
import './planning-center.css'

function PlanningCenterInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const activeTab = searchParams.get('tab') ?? 'plan-orders'

  const setTab = (tab: string) => {
    const q = new URLSearchParams(searchParams.toString())
    q.set('tab', tab)
    router.replace(`/production/planning-center?${q}`)
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header — 内容自适应高度，不参与 flex 伸缩 */}
      <PageHeading
        className="shrink-0"
        title="计划中枢"
        subtitle="需求管理、计划制定与排程调度"
        actions={<PageGuideButton />}
      />

      {/* Tabs — flex-1 填满剩余高度，CSS 全链路 flex 见 globals.css */}
      <Tabs
        activeKey={activeTab}
        onChange={setTab}
        className="planning-tabs"
        items={[
          { key: 'demands', label: '需求池', children: <DemandPool /> },
          { key: 'plan-orders', label: '计划单', children: <PlanOrderList /> },
          { key: 'schedule', label: '计划排程', children: <ScheduleView /> },
        ]}
      />
    </div>
  )
}

export function PlanningCenterPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App className="h-full">
          <Suspense
            fallback={
              <div style={{ padding: 40, textAlign: 'center', color: '#787671' }}>
                加载中...
              </div>
            }
          >
            <PlanningCenterInner />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}
