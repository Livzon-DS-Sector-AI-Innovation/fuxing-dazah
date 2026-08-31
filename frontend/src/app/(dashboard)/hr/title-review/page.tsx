import { Suspense } from 'react'
import { Alert } from 'antd'
import TitleReviewClient from '@/components/hr/TitleReviewClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function TitleReviewPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      {/* 查看权限进入管理页；纯评委进入后由页面引导到「职称评审投票」 */}
      <PermissionGuard
        permission={['hr:title:read', 'hr:title:judge']}
        fallback={<Alert type="warning" showIcon message="您没有职称评审系统的访问权限，请联系管理员赋权。" />}
      >
        <TitleReviewClient />
      </PermissionGuard>
    </Suspense>
  )
}
