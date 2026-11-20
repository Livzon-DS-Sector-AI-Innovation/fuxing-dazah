import { getAuthHeaders } from '@/lib/auth'
import { fetchPermissions, fetchRoles, fetchDepartmentTree } from '@/lib/api/permission'
import { RoleList, PermissionQueryProvider } from '@/components/permission'

export default async function RolesPage() {
  const headers = await getAuthHeaders()
  const token = headers.Authorization?.replace('Bearer ', '') || ''

  const [roles, permissionGroups, departmentTree] = await Promise.all([
    fetchRoles(token),
    fetchPermissions(token),
    fetchDepartmentTree(),
  ])

  return (
    <PermissionQueryProvider>
      <RoleList
        initialRoles={roles}
        permissionGroups={permissionGroups}
        apiToken={token}
        departmentTree={departmentTree}
      />
    </PermissionQueryProvider>
  )
}
