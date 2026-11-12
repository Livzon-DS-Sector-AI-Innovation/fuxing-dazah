import type {
  PermissionModuleGroup,
  Role,
  UserRole,
  UserPermissionDetail,
  PersonnelListResponse,
  DepartmentItem,
  DepartmentRole,
  RoleUser,
} from '@/types/permission'
import { apiGet } from '@/lib/http-client'

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

export async function fetchRoleUsers(token: string, roleId: string): Promise<RoleUser[]> {
  const res = await fetch(`${API_BASE}/api/v1/permission/roles/${roleId}/users`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取角色用户失败')
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

  // identity 端点需要登录态：走统一客户端（服务端带 Bearer / 浏览器带 cookie）
  return apiGet<PersonnelListResponse>(`${API_BASE}/api/v1/identity/personnel?${searchParams}`)
}

export async function fetchDepartments(): Promise<DepartmentItem[]> {
  return apiGet<DepartmentItem[]>(`${API_BASE}/api/v1/identity/departments`)
}

export async function fetchRoleDepartments(
  token: string,
  roleId: string,
): Promise<DepartmentRole[]> {
  const res = await fetch(`${API_BASE}/api/v1/permission/roles/${roleId}/departments`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取角色已分配部门失败')
  const json = await res.json()
  return json.data
}
