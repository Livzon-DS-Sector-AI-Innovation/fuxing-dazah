'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders } from '@/lib/auth'
import type { CreateRoleInput, UpdateRoleInput, AssignRoleInput } from '@/types/permission'

const API_BASE = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/** 后端 AppException 的 message 优先；参数校验的 detail 退化为 JSON 文本。 */
function errorMessage(err: unknown, fallback: string): string {
  const body = err as { message?: unknown; detail?: unknown } | null
  if (typeof body?.message === 'string' && body.message) return body.message
  if (body?.detail) return JSON.stringify(body.detail)
  return fallback
}

export async function createRole(data: CreateRoleInput) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/roles`, {
    method: 'POST', headers, body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = err.detail ? JSON.stringify(err.detail) : err.message || '创建角色失败'
    throw new Error(detail)
  }
  revalidatePath('/permission/roles')
  return res.json()
}

export async function updateRole(roleId: string, data: UpdateRoleInput) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/roles/${roleId}`, {
    method: 'PUT', headers, body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = err.detail ? JSON.stringify(err.detail) : err.message || '更新角色失败'
    throw new Error(detail)
  }
  revalidatePath('/permission/roles')
  return res.json()
}

export async function deleteRole(roleId: string) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/roles/${roleId}`, { method: 'DELETE', headers })
  if (!res.ok) {
    throw new Error(errorMessage(await res.json().catch(() => null), '删除角色失败'))
  }
  revalidatePath('/permission/roles')
  return res.json()
}

export async function assignRoleToUser(userId: string, data: AssignRoleInput) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/users/${userId}/roles`, {
    method: 'POST', headers, body: JSON.stringify(data),
  })
  if (!res.ok) {
    throw new Error(errorMessage(await res.json().catch(() => null), '分配角色失败'))
  }
  revalidatePath('/permission/users')
  return res.json()
}

export async function removeRoleFromUser(userId: string, roleId: string) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/users/${userId}/roles/${roleId}`, {
    method: 'DELETE', headers,
  })
  if (!res.ok) {
    throw new Error(errorMessage(await res.json().catch(() => null), '移除角色失败'))
  }
  revalidatePath('/permission/users')
  return res.json()
}

export async function assignRoleToDepartment(
  roleId: string,
  data: { feishu_department_ids: string[] },
) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/roles/${roleId}/departments`, {
    method: 'POST', headers, body: JSON.stringify(data),
  })
  if (!res.ok) {
    throw new Error(errorMessage(await res.json().catch(() => null), '分配部门角色失败'))
  }
  revalidatePath('/permission/roles')
  return res.json()
}

export async function removeRoleFromDepartment(roleId: string, feishuDepartmentId: string) {
  const headers = await getAuthHeaders()
  const res = await fetch(
    `${API_BASE}/api/v1/permission/roles/${roleId}/departments/${encodeURIComponent(feishuDepartmentId)}`,
    { method: 'DELETE', headers },
  )
  if (!res.ok) {
    throw new Error(errorMessage(await res.json().catch(() => null), '移除部门角色失败'))
  }
  revalidatePath('/permission/roles')
  return res.json()
}
