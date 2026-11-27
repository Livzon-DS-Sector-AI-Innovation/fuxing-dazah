import { Suspense } from 'react'
import { Skeleton } from 'antd'
import { DashboardClient, HrTodoStrip } from '@/components/hr'

export const dynamic = 'force-dynamic'

export default function DashboardPage() {
  return (
    // 顶部固定一条「今日待办」，下面是原来的可拖拽看板
    <div className="space-y-4">
      <Suspense fallback={<Skeleton active paragraph={{ rows: 2 }} title={false} />}>
        <HrTodoStrip />
      </Suspense>
      <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} title={false} />}>
        <DashboardClient />
      </Suspense>
    </div>
  )
}
