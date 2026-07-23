'use client'

import { Suspense } from 'react'
import { App, ConfigProvider, Tabs } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useSearchParams, useRouter } from 'next/navigation'
import { antdTheme } from '@/lib/antd-theme'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { DemandPool } from './DemandPool'
import { PlanOrderList } from './PlanOrderList'
import { ScheduleView } from './ScheduleView'

function PlanningCenterInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const activeTab = searchParams.get('tab') ?? 'demands'

  const setTab = (tab: string) => {
    const q = new URLSearchParams(searchParams.toString())
    q.set('tab', tab)
    router.replace(`/production/planning-center?${q}`)
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>
          计划中枢
        </h2>
        <span style={{ color: '#787671', fontSize: 14 }}>
          需求管理、计划制定与排程调度
        </span>
      </div>
      <Tabs
        activeKey={activeTab}
        onChange={setTab}
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
        <App>
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
