import type {
  PermissionModuleGroup,
  Role,
  UserRole,
  UserPermissionDetail,
  PersonnelListResponse,
  DepartmentItem,
} from '@/types/permission'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export async function fetchPermissions(token: string): Promise<PermissionModuleGroup[]> {
  const res = await fetch(`${API_BASE}/api/v1/permission/permissions`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`获取权限列表失败 (${res.status}): ${body}`)
  }
  const json = await res.json()
  return json.data
}

export async function fetchRoles(token: string): Promise<Role[]> {
  const res = await fetch(`${API_BASE}/api/v1/permission/roles`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`获取角色列表失败 (${res.status}): ${body}`)
  }
  const json = await res.json()
  return json.data
}

export async function fetchUserRoles(token: string, userId: string): Promise<UserRole[]> {
  const res = await fetch(`${API_BASE}/api/v1/permission/users/${userId}/roles`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取用户角色失败')
  const json = await res.json()
  return json.data
}

export async function fetchUserPermissions(token: string, userId: string): Promise<UserPermissionDetail> {
  const res = await fetch(`${API_BASE}/api/v1/permission/users/${userId}/permissions`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取用户权限失败')
  const json = await res.json()
  return json.data
}

export async function fetchPersonnel(params: {
  keyword?: string
  department_id?: string
  offset?: number
  limit?: number
}): Promise<PersonnelListResponse> {
  const searchParams = new URLSearchParams()
  if (params.keyword) searchParams.set('keyword', params.keyword)
  if (params.department_id) searchParams.set('department_id', params.department_id)
  searchParams.set('offset', String(params.offset ?? 0))
  searchParams.set('limit', String(params.limit ?? 20))

  const res = await fetch(`${API_BASE}/api/v1/identity/personnel?${searchParams}`, {
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取人员列表失败')
  const json = await res.json()
  return json.data
}

export async function fetchDepartments(): Promise<DepartmentItem[]> {
  const res = await fetch(`${API_BASE}/api/v1/identity/departments`, {
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取部门列表失败')
  const json = await res.json()
  return json.data
}
