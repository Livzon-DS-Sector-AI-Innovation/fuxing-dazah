'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders, getServerToken, getImpersonateToken } from '@/lib/auth'
import {
  CreateInspectionRouteInput, UpdateInspectionRouteInput,
  CreateInspectionTaskInput, EquipmentCheckResult,
  InspectionAIItemResult,
  RouteCheckSubmitInput, RouteLocationItem,
  CreateInspectionScheduleInput, UpdateInspectionScheduleInput,
} from '@/types/inspection'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const BASE = `${API_BASE_URL}/api/v1/equipment/inspection`

type ActionResult<T> = { success: true; data: T | null } | { success: false; error: string }

/**
 * Server Action 安全 fetch 封装。
 * 不抛异常：Server Action 中 throw 会触发 Next.js error boundary，
 * 导致页面崩溃显示 "An error occurred in the Server Components render"。
 * 改用结构化返回 { success, data } | { success, error } 让调用方安全处理。
 */
async function actionFetch<T>(
  url: string,
  options?: RequestInit & { skipRevalidate?: boolean },
): Promise<ActionResult<T>> {
  const { skipRevalidate, ...fetchInit } = options || {}
  try {
    const authHeaders = await getAuthHeaders()
    const response = await fetch(url, {
      ...fetchInit,
      headers: {
        ...authHeaders,
        ...fetchInit.headers,
      },
    })
    if (!response.ok) {
      const errorBody = await response.text().catch(() => '')
      let errorMessage = `请求失败: ${response.status} ${response.statusText}`
      try {
        const errorJson = JSON.parse(errorBody)
        if (errorJson.message) errorMessage = errorJson.message
      } catch { /* ignore */ }
      return { success: false, error: errorMessage }
    }
    // revalidatePath 在 early return 之前调用，避免 204 No Content 跳过缓存刷新
    if (!skipRevalidate) revalidatePath('/equipment/inspection')
    const text = await response.text()
    if (!text) return { success: true, data: null }
    const json = JSON.parse(text)
    return { success: true, data: (json.data ?? json) as T }
  } catch (err) {
    return { success: false, error: (err as Error).message || '请求失败' }
  }
}

/** FormData 上传的通用封装（不设 Content-Type 以支持 multipart；上传成功会刷新页面缓存） */
async function uploadPhoto(urlSuffix: string, formData: FormData): Promise<ActionResult<unknown>> {
  try {
    const token = await getServerToken()
    const impToken = await getImpersonateToken()
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`
    const response = await fetch(`${BASE}${urlSuffix}`, {
      method: 'POST',
      headers,
      body: formData,
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      return { success: false as const, error: (err as Record<string, unknown>).message as string || '上传失败' }
    }
    const json = await response.json()
    revalidatePath('/equipment/inspection')
    return { success: true as const, data: json.data }
  } catch (err) {
    return { success: false as const, error: (err as Error).message || '上传失败' }
  }
}

// ==================== 巡检线路 ====================
export async function createInspectionRoute(data: CreateInspectionRouteInput) {
  return actionFetch(`${BASE}/routes`, { method: 'POST', body: JSON.stringify(data) })
}

export async function updateInspectionRoute(id: string, data: UpdateInspectionRouteInput) {
  return actionFetch(`${BASE}/routes/${id}`, { method: 'PUT', body: JSON.stringify(data) })
}

export async function deleteInspectionRoute(id: string) {
  return actionFetch(`${BASE}/routes/${id}`, { method: 'DELETE' })
}

export async function setRouteLocations(routeId: string, locations: RouteLocationItem[]) {
  return actionFetch(`${BASE}/routes/${routeId}/locations`, {
    method: 'POST',
    body: JSON.stringify({ locations }),
  })
}

// ==================== 巡检任务 ====================
export async function createInspectionTask(data: CreateInspectionTaskInput) {
  return actionFetch(`${BASE}/tasks`, { method: 'POST', body: JSON.stringify(data) })
}

export async function startInspectionTask(id: string) {
  return actionFetch(`${BASE}/tasks/${id}/start`, { method: 'PUT' })
}

export async function completeInspectionTask(id: string) {
  return actionFetch(`${BASE}/tasks/${id}/complete`, { method: 'PUT' })
}

export async function closeInspectionTask(id: string, closureRemark?: string) {
  return actionFetch(`${BASE}/tasks/${id}/close`, {
    method: 'PUT',
    body: JSON.stringify({ closure_remark: closureRemark }),
  })
}

// ==================== 巡检执行 ====================
export async function submitEquipmentCheck(taskId: string, equipmentId: string, data: EquipmentCheckResult) {
  return actionFetch(`${BASE}/tasks/${taskId}/equipments/${equipmentId}/check`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

// ==================== 照片 ====================
export async function uploadInspectionPhoto(taskId: string, equipmentId: string, formData: FormData) {
  return uploadPhoto(`/tasks/${taskId}/equipments/${equipmentId}/photos`, formData)
}

export async function deleteInspectionPhoto(taskId: string, photoId: string) {
  return actionFetch(`${BASE}/tasks/${taskId}/photos/${photoId}`, { method: 'DELETE' })
}

// ==================== 线路巡检 ====================
export async function submitRouteCheck(taskId: string, data: RouteCheckSubmitInput) {
  return actionFetch(`${BASE}/tasks/${taskId}/route-check`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

// 任务级照片上传（线路巡检用）
export async function uploadTaskPhoto(taskId: string, formData: FormData) {
  return uploadPhoto(`/tasks/${taskId}/photos`, formData)
}

// ==================== AI 分析 ====================
export async function analyzeInspectionPhoto(
  taskId: string,
  equipmentId: string,
  imageBase64: string,
  imageMimeType: string,
): Promise<ActionResult<InspectionAIItemResult[]>> {
  return actionFetch<InspectionAIItemResult[]>(
    `${BASE}/tasks/${taskId}/equipments/${equipmentId}/ai-analyze`,
    {
      method: 'POST',
      body: JSON.stringify({ image_base64: imageBase64, image_mime_type: imageMimeType }),
      skipRevalidate: true,
    },
  )
}

// ==================== 路线定时任务 ====================
export async function createSchedule(routeId: string, data: CreateInspectionScheduleInput) {
  return actionFetch(`${BASE}/routes/${routeId}/schedules`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function updateSchedule(
  routeId: string, scheduleId: string, data: UpdateInspectionScheduleInput,
) {
  return actionFetch(`${BASE}/routes/${routeId}/schedules/${scheduleId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteSchedule(routeId: string, scheduleId: string) {
  return actionFetch(`${BASE}/routes/${routeId}/schedules/${scheduleId}`, {
    method: 'DELETE',
  })
}
