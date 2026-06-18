'use server'

import { revalidatePath } from 'next/cache'
import { getServerToken } from '@/lib/auth'
import {
  CreateInspectionRouteInput, UpdateInspectionRouteInput,
  CreateInspectionTaskInput, EquipmentCheckResult,
  InspectionRecordItem, InspectionAIItemResult,
  RouteCheckSubmitInput, RouteLocationItem,
} from '@/types/inspection'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const BASE = `${API_BASE_URL}/api/v1/equipment/inspection`

async function actionFetch<T>(url: string, options?: RequestInit): Promise<T | null> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${await getServerToken()}`,
      ...options?.headers,
    },
  })
  if (!response.ok) {
    const errorBody = await response.text().catch(() => '')
    let errorMessage = `请求失败: ${response.status} ${response.statusText}`
    try {
      const errorJson = JSON.parse(errorBody)
      if (errorJson.message) errorMessage = errorJson.message
    } catch { /* ignore */ }
    throw new Error(errorMessage)
  }
  const text = await response.text()
  if (!text) return null
  const json = JSON.parse(text)
  return json.data ?? json
}

function revalidate() {
  revalidatePath('/equipment/inspection')
}

// ==================== 巡检线路 ====================
export async function createInspectionRoute(data: CreateInspectionRouteInput) {
  const result = await actionFetch(`${BASE}/routes`, { method: 'POST', body: JSON.stringify(data) })
  revalidate()
  return result
}

export async function updateInspectionRoute(id: string, data: UpdateInspectionRouteInput) {
  const result = await actionFetch(`${BASE}/routes/${id}`, { method: 'PUT', body: JSON.stringify(data) })
  revalidate()
  return result
}

export async function deleteInspectionRoute(id: string) {
  const result = await actionFetch(`${BASE}/routes/${id}`, { method: 'DELETE' })
  revalidate()
  return result
}

export async function setRouteLocations(routeId: string, locations: RouteLocationItem[]) {
  const result = await actionFetch(`${BASE}/routes/${routeId}/locations`, {
    method: 'POST',
    body: JSON.stringify({ locations }),
  })
  revalidate()
  return result
}

// ==================== 巡检任务 ====================
export async function createInspectionTask(data: CreateInspectionTaskInput) {
  const result = await actionFetch(`${BASE}/tasks`, { method: 'POST', body: JSON.stringify(data) })
  revalidate()
  return result
}

export async function startInspectionTask(id: string) {
  const result = await actionFetch(`${BASE}/tasks/${id}/start`, { method: 'PUT' })
  revalidate()
  return result
}

export async function completeInspectionTask(id: string) {
  const result = await actionFetch(`${BASE}/tasks/${id}/complete`, { method: 'PUT' })
  revalidate()
  return result
}

export async function closeInspectionTask(id: string, closureRemark?: string) {
  const result = await actionFetch(`${BASE}/tasks/${id}/close`, {
    method: 'PUT',
    body: JSON.stringify({ closure_remark: closureRemark }),
  })
  revalidate()
  return result
}

// ==================== 巡检执行 ====================
export async function submitEquipmentCheck(taskId: string, equipmentId: string, data: EquipmentCheckResult) {
  const result = await actionFetch(`${BASE}/tasks/${taskId}/equipments/${equipmentId}/check`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidate()
  return result
}

// ==================== 照片 ====================
export async function uploadInspectionPhoto(taskId: string, equipmentId: string, formData: FormData) {
  const token = await getServerToken()
  const response = await fetch(`${BASE}/tasks/${taskId}/equipments/${equipmentId}/photos`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error((err as Record<string, unknown>).message as string || '上传失败')
  }
  revalidate()
  const json = await response.json()
  return json.data
}

export async function deleteInspectionPhoto(taskId: string, photoId: string) {
  const result = await actionFetch(`${BASE}/tasks/${taskId}/photos/${photoId}`, { method: 'DELETE' })
  revalidate()
  return result
}

// ==================== 线路巡检 ====================
export async function submitRouteCheck(taskId: string, data: RouteCheckSubmitInput) {
  const result = await actionFetch(`${BASE}/tasks/${taskId}/route-check`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidate()
  return result
}

// 任务级照片上传（线路巡检用）
export async function uploadTaskPhoto(taskId: string, formData: FormData) {
  const token = await getServerToken()
  const response = await fetch(`${BASE}/tasks/${taskId}/photos`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error((err as Record<string, unknown>).message as string || '上传失败')
  }
  revalidate()
  const json = await response.json()
  return json.data
}

// ==================== AI 分析 ====================
export async function analyzeInspectionPhoto(
  taskId: string,
  equipmentId: string,
  imageBase64: string,
  imageMimeType: string,
): Promise<InspectionAIItemResult[]> {
  const result = await actionFetch<InspectionAIItemResult[]>(
    `${BASE}/tasks/${taskId}/equipments/${equipmentId}/ai-analyze`,
    {
      method: 'POST',
      body: JSON.stringify({ image_base64: imageBase64, image_mime_type: imageMimeType }),
    },
  )
  return result ?? []
}
