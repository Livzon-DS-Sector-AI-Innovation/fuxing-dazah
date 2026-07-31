'use server'

import { revalidatePath } from 'next/cache'
import { cookies } from 'next/headers'
import { fetchHrApi } from './_helpers'
import { API_BASE } from './_utils'

// ─── 数据管理 ───

export async function fetchDataTables(): Promise<{ data: unknown[] }> {
  const cookieStore = await cookies()
  const allCookies = cookieStore.getAll().map(c => `${c.name}=${c.value}`).join('; ')
  const res = await fetch(`${API_BASE}/hr/data-management/tables`, {
    headers: { Cookie: allCookies },
    cache: 'no-store',
  })
  const text = await res.text()
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`)
  }
  try {
    return JSON.parse(text)
  } catch {
    throw new Error(`Invalid JSON response: ${text.slice(0, 200)}`)
  }
}

export async function clearDataTables(tables: string[]): Promise<{ message: string }> {
  const res = await fetchHrApi<{ message: string }>('/hr/data-management/clear', {
    method: 'POST',
    body: JSON.stringify(tables),
    errorMessage: '操作失败',
  })
  revalidatePath('/hr/settings')
  return res
}

// ─── 系统设置 ───

export async function getSystemSettings(): Promise<{ data: Record<string, unknown> }> {
  return fetchHrApi('/hr/system-settings', { errorMessage: '加载系统设置失败' })
}

export async function updateSystemSettings(data: Record<string, unknown>): Promise<{ code: number; message: string }> {
  return fetchHrApi('/hr/system-settings', {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '保存失败',
  })
}

// ─── 通知记录 ───

export async function fetchNotificationLogs(params?: { page_size?: number }): Promise<{ data: unknown[] }> {
  const pageSize = params?.page_size || 100
  return fetchHrApi(`/hr/notification-logs?page_size=${pageSize}`, { errorMessage: '获取通知记录失败' })
}

// ─── 用户多部门访问授权 ───

export async function fetchTrainingAdmins(): Promise<{ data: unknown[] }> {
  return fetchHrApi('/hr/training-admins', { errorMessage: '加载培训管理员列表失败' })
}

export async function fetchHrDepartments(): Promise<{ data: string[] }> {
  return fetchHrApi('/hr/departments?page_size=200', { errorMessage: '加载部门列表失败' })
}

export async function fetchUserDeptAccess(params?: { page?: number; page_size?: number }): Promise<{ data: unknown[]; meta: unknown }> {
  const page = params?.page || 1
  const pageSize = params?.page_size || 50
  return fetchHrApi(`/hr/user-department-access?page=${page}&page_size=${pageSize}`, { errorMessage: '加载访问授权失败' })
}

export async function createUserDeptAccess(data: { user_id: string; department: string }): Promise<{ message: string }> {
  const res = await fetchHrApi('/hr/user-department-access', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '添加授权失败',
  })
  revalidatePath('/hr/settings')
  return res
}

export async function deleteUserDeptAccess(id: string): Promise<{ message: string }> {
  const res = await fetchHrApi(`/hr/user-department-access/${id}`, {
    method: 'DELETE',
    errorMessage: '移除授权失败',
  })
  revalidatePath('/hr/settings')
  return res
}
