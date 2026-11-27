import PageHeader from '@/components/hr/PageHeader'
import { Suspense } from 'react'
import { Alert } from 'antd'
import PerformanceCategoryClient from '@/components/hr/PerformanceCategoryClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function CategoriesPage() {
  return <div className="space-y-6">
    <PageHeader title="考核项目配置" description="配置考核项目名称、权重、负责人" />
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission="hr:performance:read"
        fallback={<Alert type="warning" showIcon title="您没有绩效考核的查看权限，请联系管理员赋权。" />}
      >
        <PerformanceCategoryClient />
      </PermissionGuard>
    </Suspense>
  </div>
}
