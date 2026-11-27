import { Alert } from 'antd'
import { getAuthHeaders } from '@/lib/auth'
import {
  PermissionGuard,
  PermissionQueryProvider,
  UserPermissionView,
} from '@/components/permission'

export default async function UsersPage() {
  const headers = await getAuthHeaders()
  const token = headers.Authorization?.replace('Bearer ', '') || ''

  return (
    <PermissionGuard
      permission={['permission:user:view', 'permission:user:assign', 'permission:role:manage']}
      fallback={<Alert type="warning" showIcon title="您没有用户权限的查看权限，请联系管理员赋权。" />}
    >
      <PermissionQueryProvider>
        <UserPermissionView apiToken={token} />
      </PermissionQueryProvider>
    </PermissionGuard>
  )
}
