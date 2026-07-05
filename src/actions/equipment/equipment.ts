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

type ActionResult<T = unknown> = { success: true; data: T | null } | { success: false; error: string }

async function actionFetch(
  url: string,
  options?: RequestInit,
): Promise<ActionResult> {
  try {
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
      let errorMessage = `请求失败: ${response.status}`
      try {
        const errorJson = JSON.parse(errorBody)
        if (errorJson.message) {
          errorMessage = errorJson.message
          if (errorJson.detail) errorMessage += `: ${errorJson.detail}`
          if (errorJson.request_id) errorMessage += ` (编号: ${errorJson.request_id})`
        }
      } catch { /* ignore */ }
      return { success: false, error: errorMessage }
    }
    const text = await response.text()
    if (!text) return { success: true, data: null }
    const json = JSON.parse(text)
    return { success: true, data: json.data ?? json }
  } catch (err) {
    return { success: false, error: (err as Error).message || '请求失败' }
  }
}

// 设备分类
export async function createCategory(data: CreateCategoryInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/categories`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateCategory(id: string, data: UpdateCategoryInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/categories/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteCategory(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/categories/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// 位置管理
export async function createLocation(data: CreateLocationInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/locations`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateLocation(id: string, data: UpdateLocationInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/locations/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteLocation(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/locations/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// 设备管理
export async function createEquipment(data: CreateEquipmentInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/equipments`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateEquipment(id: string, data: UpdateEquipmentInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/equipments/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteEquipment(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/equipments/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 故障代码 ====================
type FailureCodePath = 'symptoms' | 'causes' | 'actions'

export async function createFailureCode(path: FailureCodePath, data: CreateFailureCodeInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${path}`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateFailureCode(path: FailureCodePath, id: string, data: UpdateFailureCodeInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${path}/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteFailureCode(path: FailureCodePath, id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${path}/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 维修工单 ====================
export async function createWorkOrder(data: CreateWorkOrderInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateWorkOrder(id: string, data: UpdateWorkOrderInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function assignWorkOrder(id: string, data: AssignWorkOrderInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/assign`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function startWorkOrder(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/start`, {
    method: 'PUT',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function completeWorkOrder(id: string, data: CompleteWorkOrderInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/complete`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function verifyWorkOrder(id: string, data: VerifyWorkOrderInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/verify`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function closeWorkOrder(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/close`, {
    method: 'PUT',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 校准计划 ====================
export async function createCalibrationPlan(data: CreateCalibrationPlanInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateCalibrationPlan(id: string, data: UpdateCalibrationPlanInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteCalibrationPlan(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 校准记录 ====================
export async function createCalibrationRecord(data: CreateCalibrationRecordInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/records`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 备件管理 ====================
export async function createSparePart(data: CreateSparePartInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateSparePart(id: string, data: UpdateSparePartInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteSparePart(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function stockInbound(sparePartId: string, data: StockInboundInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${sparePartId}/stock/inbound`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function stockAdjust(sparePartId: string, data: StockAdjustInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${sparePartId}/stock/adjust`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 维护计划 ====================
export async function createMaintenancePlan(data: CreateMaintenancePlanInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateMaintenancePlan(id: string, data: UpdateMaintenancePlanInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteMaintenancePlan(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 巡检模板 ====================
export async function createInspectionTemplate(data: CreateInspectionTemplateInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateInspectionTemplate(id: string, data: UpdateInspectionTemplateInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteInspectionTemplate(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function createInspectionTemplateItem(templateId: string, data: CreateInspectionTemplateItemInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${templateId}/items`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function updateInspectionTemplateItem(itemId: string, data: UpdateInspectionTemplateItemInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/items/${itemId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function deleteInspectionTemplateItem(itemId: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/items/${itemId}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

export async function completeInspection(workOrderId: string, data: InspectionCompleteInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/complete/${workOrderId}`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 工单物料领用 ====================
export async function consumeMaterials(workOrderId: string, data: MaterialConsumeInput): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/materials`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 工单图片 ====================
export async function uploadWorkOrderImages(workOrderId: string, formData: FormData): Promise<ActionResult> {
  try {
    const token = await getServerToken()
    const impToken = await getImpersonateToken()
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`
    const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/images`, {
      method: 'POST',
      headers,
      body: formData,
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      return { success: false, error: (err as any).message || '上传失败' }
    }
    revalidatePath('/equipment')
    const json = await response.json()
    return { success: true, data: json.data }
  } catch (err) {
    return { success: false, error: (err as Error).message || '上传失败' }
  }
}

export async function deleteWorkOrderImage(workOrderId: string, imageId: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/images/${imageId}`, {
    method: 'DELETE',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 抢单 ====================
export async function claimWorkOrder(id: string): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}/claim`, {
    method: 'PUT',
  })
  if (result.success) revalidatePath('/equipment')
  return result
}

// ==================== 配置 ====================
export async function updateClaimTimeoutConfig(data: { emergency?: number; high?: number; medium?: number; low?: number }): Promise<ActionResult> {
  const result = await actionFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/config/claim-timeout`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (result.success) revalidatePath('/equipment')
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

export async function downloadImportTemplate(): Promise<ActionResult<string>> {
  try {
    const authHeaders = await getAuthHeaders()
    const res = await fetch(`${API_BASE_URL}/api/v1/equipment/equipments/import/template`, {
      headers: authHeaders,
    })
    if (!res.ok) return { success: false, error: '下载模板失败' }
    const blob = await res.blob()
    const arrayBuffer = await blob.arrayBuffer()
    return { success: true, data: Buffer.from(arrayBuffer).toString('base64') }
  } catch (err) {
    return { success: false, error: (err as Error).message || '下载模板失败' }
  }
}

export async function importEquipments(formData: FormData): Promise<ActionResult<ImportResult>> {
  try {
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
      return { success: false, error: (err as any).message || '导入失败' }
    }
    const json = await res.json()
    const data = (json.data ?? json) as ImportResult
    revalidatePath('/equipment')
    return { success: true, data }
  } catch (err) {
    return { success: false, error: (err as Error).message || '导入失败' }
  }
}
