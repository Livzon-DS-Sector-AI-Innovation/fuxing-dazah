'use server'

import { revalidatePath } from 'next/cache'
import {
  CreateCategoryInput, UpdateCategoryInput, CreateLocationInput, UpdateLocationInput, CreateEquipmentInput, UpdateEquipmentInput,
  CreateFailureCodeInput, UpdateFailureCodeInput,
  CreateWorkOrderInput, AssignWorkOrderInput, CompleteWorkOrderInput, VerifyWorkOrderInput,
  CreateCalibrationPlanInput, UpdateCalibrationPlanInput, CreateCalibrationRecordInput,
} from '@/types/equipment'

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000'

async function actionFetch<T>(url: string, options?: RequestInit): Promise<T | null> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      // TODO: 添加认证头
      // Authorization: `Bearer ${await getServerToken()}`,
      ...options?.headers,
    },
  })
  if (!response.ok) {
    const errorBody = await response.text().catch(() => '')
    let errorMessage = `请求失败: ${response.status} ${response.statusText}`
    try {
      const errorJson = JSON.parse(errorBody)
      if (errorJson.message) errorMessage = errorJson.message
    } catch {}
    throw new Error(errorMessage)
  }
  const text = await response.text()
  if (!text) return null
  const json = JSON.parse(text)
  return json.data ?? json
}

// 设备分类
export async function createCategory(data: CreateCategoryInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/categories`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateCategory(id: string, data: UpdateCategoryInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/categories/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteCategory(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/categories/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

// 位置管理
export async function createLocation(data: CreateLocationInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/locations`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateLocation(id: string, data: UpdateLocationInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/locations/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteLocation(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/locations/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

// 设备管理
export async function createEquipment(data: CreateEquipmentInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/equipments`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateEquipment(id: string, data: UpdateEquipmentInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/equipments/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteEquipment(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/equipments/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 故障代码 ====================
type FailureCodePath = 'symptoms' | 'causes' | 'actions'

export async function createFailureCode(path: FailureCodePath, data: CreateFailureCodeInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${path}`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateFailureCode(path: FailureCodePath, id: string, data: UpdateFailureCodeInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${path}/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteFailureCode(path: FailureCodePath, id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${path}/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 维修工单 ====================
export async function createWorkOrder(data: CreateWorkOrderInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function assignWorkOrder(id: string, data: AssignWorkOrderInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/assign`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function startWorkOrder(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/start`, {
    method: 'PUT',
  })
  revalidatePath('/equipment')
  return result
}

export async function completeWorkOrder(id: string, data: CompleteWorkOrderInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/complete`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function verifyWorkOrder(id: string, data: VerifyWorkOrderInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/verify`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function closeWorkOrder(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/close`, {
    method: 'PUT',
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 校准计划 ====================
export async function createCalibrationPlan(data: CreateCalibrationPlanInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateCalibrationPlan(id: string, data: UpdateCalibrationPlanInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteCalibrationPlan(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 校准记录 ====================
export async function createCalibrationRecord(data: CreateCalibrationRecordInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/records`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}
