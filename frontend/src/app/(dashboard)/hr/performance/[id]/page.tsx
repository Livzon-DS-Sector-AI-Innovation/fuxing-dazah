import PageHeader from '@/components/hr/PageHeader'
import { Suspense } from 'react'
import { Alert } from 'antd'
import PerformanceFormClient, { PerformanceBackButton } from '@/components/hr/PerformanceFormClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function PerformanceDetailPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="绩效考核详情" description="编辑自评与领导评分"
        actions={<PerformanceBackButton />} />
      <Suspense fallback={<div className="h-64" />}>
        <PermissionGuard
          permission="hr:performance:read"
          fallback={<Alert type="warning" showIcon title="您没有绩效考核的查看权限，请联系管理员赋权。" />}
        >
          <PerformanceFormClient />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
