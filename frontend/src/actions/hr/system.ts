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

// ─── 仪表盘 / 通知记录 ───

export async function fetchDashboardStats(): Promise<{ data: Record<string, unknown> }> {
  return fetchHrApi('/hr/dashboard-stats', { errorMessage: '获取统计数据失败' })
}

export async function fetchNotificationLogs(params?: { page_size?: number }): Promise<{ data: unknown[] }> {
  const pageSize = params?.page_size || 100
  return fetchHrApi(`/hr/notification-logs?page_size=${pageSize}`, { errorMessage: '获取通知记录失败' })
}
