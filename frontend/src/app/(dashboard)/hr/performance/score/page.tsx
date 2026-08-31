import { Suspense } from 'react'
import { Alert } from 'antd'
import PerformanceCategoryScoreClient from '@/components/hr/PerformanceCategoryScoreClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function ScorePage({ searchParams }: { searchParams: { month?: string } }) {
  return <div className="space-y-6">
    <div><h1 className="text-[22px] font-semibold mb-2">考核项目评分</h1><p className="text-sm text-gray-500">各项目负责人给部门打分</p></div>
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission="hr:performance:read"
        fallback={<Alert type="warning" showIcon message="您没有绩效考核的查看权限，请联系管理员赋权。" />}
      >
        <PerformanceCategoryScoreClient initialMonth={searchParams?.month} />
      </PermissionGuard>
    </Suspense>
  </div>
}
