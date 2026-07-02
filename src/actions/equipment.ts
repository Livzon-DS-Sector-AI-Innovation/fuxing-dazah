'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders, getServerToken, getImpersonateToken } from '@/lib/auth'
import {
  CreateCategoryInput, UpdateCategoryInput, CreateLocationInput, UpdateLocationInput, CreateEquipmentInput, UpdateEquipmentInput,
  CreateFailureCodeInput, UpdateFailureCodeInput,
  CreateWorkOrderInput, UpdateWorkOrderInput, AssignWorkOrderInput, CompleteWorkOrderInput, VerifyWorkOrderInput,
  CreateCalibrationPlanInput, UpdateCalibrationPlanInput, CreateCalibrationRecordInput,
  CreateSparePartInput, UpdateSparePartInput, StockInboundInput, StockAdjustInput,
  CreateMaintenancePlanInput, UpdateMaintenancePlanInput,
  CreateInspectionTemplateInput, UpdateInspectionTemplateInput,
  CreateInspectionTemplateItemInput, UpdateInspectionTemplateItemInput,
  InspectionCompleteInput, MaterialConsumeInput,
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

export async function updateWorkOrder(id: string, data: UpdateWorkOrderInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}`, {
    method: 'PUT',
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

// ==================== 备件管理 ====================
export async function createSparePart(data: CreateSparePartInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateSparePart(id: string, data: UpdateSparePartInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteSparePart(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

export async function stockInbound(sparePartId: string, data: StockInboundInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${sparePartId}/stock/inbound`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function stockAdjust(sparePartId: string, data: StockAdjustInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${sparePartId}/stock/adjust`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 维护计划 ====================
export async function createMaintenancePlan(data: CreateMaintenancePlanInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateMaintenancePlan(id: string, data: UpdateMaintenancePlanInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteMaintenancePlan(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 巡检模板 ====================
export async function createInspectionTemplate(data: CreateInspectionTemplateInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateInspectionTemplate(id: string, data: UpdateInspectionTemplateInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteInspectionTemplate(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

export async function createInspectionTemplateItem(templateId: string, data: CreateInspectionTemplateItemInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${templateId}/items`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function updateInspectionTemplateItem(itemId: string, data: UpdateInspectionTemplateItemInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/items/${itemId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

export async function deleteInspectionTemplateItem(itemId: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/items/${itemId}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

export async function completeInspection(workOrderId: string, data: InspectionCompleteInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/complete/${workOrderId}`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 工单物料领用 ====================
export async function consumeMaterials(workOrderId: string, data: MaterialConsumeInput) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/materials`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 工单图片 ====================
export async function uploadWorkOrderImages(workOrderId: string, formData: FormData) {
  const token = await getServerToken()
  const impToken = await getImpersonateToken()
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`
  const result = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/images`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!result.ok) {
    const err = await result.json().catch(() => ({}))
    throw new Error((err as any).message || '上传失败')
  }
  revalidatePath('/equipment')
  const json = await result.json()
  return json.data
}

export async function deleteWorkOrderImage(workOrderId: string, imageId: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/images/${imageId}`, {
    method: 'DELETE',
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 抢单 ====================
export async function claimWorkOrder(id: string) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/claim`, {
    method: 'PUT',
  })
  revalidatePath('/equipment')
  return result
}

// ==================== 配置 ====================
export async function updateClaimTimeoutConfig(data: { emergency?: number; high?: number; medium?: number; low?: number }) {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/config/claim-timeout`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  revalidatePath('/equipment')
  return result
}

// ==================== Excel 导入 ====================
export interface ImportRowError {
  row: number
  message: string
}

export interface ImportResult {
  imported: number
  skipped: number
  errors: ImportRowError[]
  warnings: ImportRowError[]
}

export async function downloadImportTemplate(): Promise<string> {
  const authHeaders = await getAuthHeaders()
  const res = await fetch(`${API_BASE_URL}/api/v1/equipment/equipments/import/template`, {
    headers: authHeaders,
  })
  if (!res.ok) throw new Error('下载模板失败')
  const blob = await res.blob()
  const arrayBuffer = await blob.arrayBuffer()
  return Buffer.from(arrayBuffer).toString('base64')
}

export async function importEquipments(formData: FormData): Promise<ImportResult> {
  const authHeaders = await getAuthHeaders()
  // 文件上传不能设 Content-Type，fetch 会自动加 multipart/form-data + boundary
  const { 'Content-Type': _ct, ...uploadHeaders } = authHeaders
  const res = await fetch(`${API_BASE_URL}/api/v1/equipment/equipments/import`, {
    method: 'POST',
    headers: uploadHeaders,
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).message || '导入失败')
  }
  const json = await res.json()
  const data = json.data ?? json
  revalidatePath('/equipment')
  return data as ImportResult
}
