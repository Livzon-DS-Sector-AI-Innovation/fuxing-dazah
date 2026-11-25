import { Suspense } from 'react'
import { Alert } from 'antd'
import { PermissionGuard } from '@/components/permission/PermissionGuard'
import ContractLedgerClient from '@/components/hr/ContractLedgerClient'

export default function LaborContractsPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<div className="h-64" />}>
        <PermissionGuard
          permission="hr:contract:read"
          fallback={<Alert type="warning" showIcon title="您没有劳动合同台账的查看权限，请联系管理员赋权。" />}
        >
          <ContractLedgerClient />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
