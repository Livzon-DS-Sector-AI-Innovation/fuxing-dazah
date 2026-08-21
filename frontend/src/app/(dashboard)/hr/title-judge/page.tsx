import { Suspense } from 'react'
import { Alert } from 'antd'
import TitleJudgeClient from '@/components/hr/TitleJudgeClient'
import { PermissionGuard } from '@/components/permission/PermissionGuard'

export default function TitleJudgePage() {
  return (
    <Suspense fallback={<div className="h-64" />}>
      <PermissionGuard
        permission="hr:title:judge"
        fallback={<Alert type="warning" showIcon message="您没有评委投票权限，请联系管理员将您加入部门评审组并赋权。" />}
      >
        <TitleJudgeClient />
      </PermissionGuard>
    </Suspense>
  )
}
