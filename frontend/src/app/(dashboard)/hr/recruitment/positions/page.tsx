import { Suspense } from 'react'
import { Alert } from 'antd'
import { PermissionGuard } from '@/components/permission/PermissionGuard'
import { RecruitmentPositionsClient } from '@/components/hr/recruitment-positions'

export const metadata = { title: '招聘岗位信息' }

export default function RecruitmentPositionsPage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission="hr:recruitment:read"
        fallback={<Alert type="warning" showIcon title="您没有招聘管理的查看权限，请联系管理员赋权。" />}
      >
        <RecruitmentPositionsClient />
      </PermissionGuard>
    </Suspense>
  )
}
