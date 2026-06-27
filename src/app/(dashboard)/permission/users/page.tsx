import { getAuthHeaders } from '@/lib/auth'
import { fetchRoles } from '@/lib/api/permission'
import { UserPermissionView } from '@/components/permission'

export default async function UsersPage() {
  const headers = await getAuthHeaders()
  const token = headers.Authorization?.replace('Bearer ', '') || ''

  const availableRoles = await fetchRoles(token)

  return <UserPermissionView apiToken={token} availableRoles={availableRoles} />
}
