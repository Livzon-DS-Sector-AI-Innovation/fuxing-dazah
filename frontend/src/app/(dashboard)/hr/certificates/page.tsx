import { Suspense } from 'react'
import { Alert } from 'antd'
import { PermissionGuard } from '@/components/permission/PermissionGuard'
import CertificatesLedgerClient from '@/components/hr/CertificatesLedgerClient'

export default function CertificatesPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<div className="h-64" />}>
        <PermissionGuard
          permission="hr:certificate:read"
          fallback={<Alert type="warning" showIcon title="您没有证件资料库的查看权限，请联系管理员赋权。" />}
        >
          <CertificatesLedgerClient />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
