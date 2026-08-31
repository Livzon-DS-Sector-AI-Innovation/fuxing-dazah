import { Suspense } from 'react'
import { Alert } from 'antd'
import RecruitmentClient from '@/components/hr/RecruitmentClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function RecruitmentPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission="hr:recruitment:read"
        fallback={<Alert type="warning" showIcon message="您没有招聘管理的查看权限，请联系管理员赋权。" />}
      >
        <RecruitmentClient />
      </PermissionGuard>
    </Suspense>
  )
}
