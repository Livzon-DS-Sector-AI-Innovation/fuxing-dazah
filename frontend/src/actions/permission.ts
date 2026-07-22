'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders } from '@/lib/auth'
import type { CreateRoleInput, UpdateRoleInput, AssignRoleInput } from '@/types/permission'

const API_BASE = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

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
  if (!res.ok) throw new Error('删除角色失败')
  revalidatePath('/permission/roles')
  return res.json()
}

export async function assignRoleToUser(userId: string, data: AssignRoleInput) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/users/${userId}/roles`, {
    method: 'POST', headers, body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('分配角色失败')
  revalidatePath('/permission/users')
  return res.json()
}

export async function removeRoleFromUser(userId: string, roleId: string) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}/api/v1/permission/users/${userId}/roles/${roleId}`, {
    method: 'DELETE', headers,
  })
  if (!res.ok) throw new Error('移除角色失败')
  revalidatePath('/permission/users')
  return res.json()
}
