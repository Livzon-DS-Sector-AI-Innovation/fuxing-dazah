import { Suspense } from 'react'
import { Alert } from 'antd'
import TitleReviewClient from '@/components/hr/TitleReviewClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function TitleReviewPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission={['hr:title:read']}
        fallback={<Alert type="warning" showIcon message="您没有职称评审系统的访问权限，请联系管理员赋权。" />}
      >
        <TitleReviewClient />
      </PermissionGuard>
    </Suspense>
  )
}
