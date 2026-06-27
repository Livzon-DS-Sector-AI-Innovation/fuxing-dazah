import { getAuthHeaders } from '@/lib/auth'
import { fetchPermissions, fetchRoles } from '@/lib/api/permission'
import { RoleList } from '@/components/permission'

export default async function RolesPage() {
  const headers = await getAuthHeaders()
  const token = headers.Authorization?.replace('Bearer ', '') || ''

  const [roles, permissionGroups] = await Promise.all([
    fetchRoles(token),
    fetchPermissions(token),
  ])

  return <RoleList initialRoles={roles} permissionGroups={permissionGroups} />
}
