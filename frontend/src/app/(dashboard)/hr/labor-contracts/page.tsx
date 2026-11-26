import { Suspense } from 'react'
import { Alert, Tabs } from 'antd'
import { PermissionGuard } from '@/components/permission/PermissionGuard'
import ContractLedgerClient from '@/components/hr/ContractLedgerClient'
import ContractArchiveClient from '@/components/hr/labor-contract/ContractArchiveClient'

export default function LaborContractsPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<div className="h-64" />}>
        <PermissionGuard
          permission="hr:contract:read"
          fallback={<Alert type="warning" showIcon title="您没有劳动合同台账的查看权限，请联系管理员赋权。" />}
        >
          {/* 切换页签即重新挂载：在档案库归档后切回台账，「归档」列立即是最新状态 */}
          <Tabs
            defaultActiveKey="ledger"
            destroyOnHidden
            items={[
              { key: 'ledger', label: '在职合同台账', children: <ContractLedgerClient /> },
              { key: 'archive', label: '电子档案库', children: <ContractArchiveClient /> },
            ]}
          />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
