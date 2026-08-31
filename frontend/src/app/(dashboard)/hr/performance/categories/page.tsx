import { Suspense } from 'react'
import { Alert } from 'antd'
import PerformanceCategoryClient from '@/components/hr/PerformanceCategoryClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function CategoriesPage() {
  return <div className="space-y-6">
    <div><h1 className="text-[22px] font-semibold mb-2">考核项目配置</h1><p className="text-sm text-gray-500">配置考核项目名称、权重、负责人</p></div>
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission="hr:performance:read"
        fallback={<Alert type="warning" showIcon message="您没有绩效考核的查看权限，请联系管理员赋权。" />}
      >
        <PerformanceCategoryClient />
      </PermissionGuard>
    </Suspense>
  </div>
}
