import PageHeader from '@/components/hr/PageHeader'
import { Suspense } from 'react'
import { Alert } from 'antd'
import PerformanceListClient from '@/components/hr/PerformanceListClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function PerformancePage() {
  return (
    <div className="space-y-6">
      <PageHeader title="月度绩效考核" description="部门负责人自评与分管领导评分" />
      <Suspense fallback={<div className="h-64" />}>
        <PermissionGuard
          permission="hr:performance:read"
          fallback={<Alert type="warning" showIcon title="您没有绩效考核的查看权限，请联系管理员赋权。" />}
        >
          <PerformanceListClient />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
