'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders } from '@/lib/auth'
import type {
  CreateRoleInput, UpdateRoleInput, AddPersonnelInput,
  AssignRolesInput, AssignCategoriesInput,
} from '@/types/equipment'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

async function actionFetch<T>(url: string, options?: RequestInit): Promise<T | null> {
  const authHeaders = await getAuthHeaders()
  const response = await fetch(url, {
    ...options,
    headers: {
      ...authHeaders,
      ...options?.headers,
    },
  })
  if (!response.ok) {
    const errorBody = await response.text().catch(() => '')
    let errorMessage = `请求失败: ${response.status} ${response.statusText}`
    try {
      const errorJson = JSON.parse(errorBody)
      if (errorJson.message) errorMessage = errorJson.message
    } catch { /* ignore parse error */ }
    throw new Error(errorMessage)
  }
  const text = await response.text()
  if (!text) return null
  const json = JSON.parse(text)
  return json.data ?? json
}

// ── 角色 Actions ──

export async function createRole(data: CreateRoleInput) {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel/roles`,
    { method: 'POST', body: JSON.stringify(data) },
  )
  revalidatePath('/equipment/personnel')
  return result
}

export async function updateRole(id: string, data: UpdateRoleInput) {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel/roles/${id}`,
    { method: 'PUT', body: JSON.stringify(data) },
  )
  revalidatePath('/equipment/personnel')
  return result
}

export async function deleteRole(id: string) {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel/roles/${id}`,
    { method: 'DELETE' },
  )
  revalidatePath('/equipment/personnel')
  return result
}

// ── 人员 Actions ──

export async function addPersonnel(data: AddPersonnelInput) {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel`,
    { method: 'POST', body: JSON.stringify(data) },
  )
  revalidatePath('/equipment/personnel')
  return result
}

export async function deletePersonnel(id: string) {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel/${id}`,
    { method: 'DELETE' },
  )
  revalidatePath('/equipment/personnel')
  return result
}

export async function assignRoles(
  personnelId: string, data: AssignRolesInput,
) {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel/${personnelId}/roles`,
    { method: 'POST', body: JSON.stringify(data) },
  )
  revalidatePath('/equipment/personnel')
  return result
}

export async function assignCategories(
  personnelId: string, data: AssignCategoriesInput,
) {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel/${personnelId}/categories`,
    { method: 'POST', body: JSON.stringify(data) },
  )
  revalidatePath('/equipment/personnel')
  return result
}

export async function refreshFeishu() {
  const result = await actionFetch(
    `${API_BASE_URL}/api/v1/equipment/personnel/refresh-feishu`,
    { method: 'POST' },
  )
  revalidatePath('/equipment/personnel')
  return result
}
