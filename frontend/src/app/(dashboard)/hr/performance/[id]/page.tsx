import { Suspense } from 'react'
import { Alert } from 'antd'
import PerformanceFormClient from '@/components/hr/PerformanceFormClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function PerformanceDetailPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">绩效考核详情</h1>
        <p className="text-[14px] text-[var(--color-steel)]">编辑自评与领导评分</p>
      </div>
      <Suspense fallback={<div className="h-64" />}>
        <PermissionGuard
          permission="hr:performance:read"
          fallback={<Alert type="warning" showIcon message="您没有绩效考核的查看权限，请联系管理员赋权。" />}
        >
          <PerformanceFormClient />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
