import PageHeader from '@/components/hr/PageHeader'
import { Suspense } from 'react'
import { Alert } from 'antd'
import PerformanceCategoryScoreClient from '@/components/hr/PerformanceCategoryScoreClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default async function ScorePage({ searchParams }: { searchParams: Promise<{ month?: string }> }) {
  // Next 16 的 searchParams 是 Promise，须 await 后才能取到 ?month=（此前同步读取恒为 undefined）
  const { month } = await searchParams
  return <div className="space-y-6">
    <PageHeader title="考核项目评分" description="各项目负责人给部门打分" />
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission="hr:performance:read"
        fallback={<Alert type="warning" showIcon title="您没有绩效考核的查看权限，请联系管理员赋权。" />}
      >
        <PerformanceCategoryScoreClient initialMonth={month} />
      </PermissionGuard>
    </Suspense>
  </div>
}
