import { Suspense } from 'react'
import { Alert, Skeleton } from 'antd'
import { PermissionGuard } from '@/components/permission/PermissionGuard'
import ContractWorkspace from '@/components/hr/labor-contract/ContractWorkspace'

export default function LaborContractsPage() {
  return (
    <div className="space-y-6">
      {/* 外壳要读网址参数（?todo= 深链），必须包在 Suspense 里；加载期间给骨架屏而不是空白 */}
      <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} title={false} />}>
        <PermissionGuard
          permission="hr:contract:read"
          fallback={<Alert type="warning" showIcon title="您没有劳动合同台账的查看权限，请联系管理员赋权。" />}
        >
          <ContractWorkspace />
        </PermissionGuard>
      </Suspense>
    </div>
  )
}
