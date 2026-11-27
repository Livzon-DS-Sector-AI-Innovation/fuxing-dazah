import { Suspense } from 'react'
import { Alert } from 'antd'
import { PermissionGuard } from '@/components/permission/PermissionGuard'
import EmployeeDetailClient from '@/components/hr/employee/EmployeeDetailClient'

export default async function EmployeeDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <div className="space-y-6">
      <Suspense fallback={<div className="h-64" />}>
        <PermissionGuard
          permission="hr:profile:read"
          fallback={<Alert type="warning" showIcon title="您没有员工档案的查看权限，请联系管理员赋权。" />}
        >
          <EmployeeDetailClient employeeId={id} />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
