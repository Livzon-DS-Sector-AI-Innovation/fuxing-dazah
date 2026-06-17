'use client'

import {
  EquipmentCategory,
  Location,
  EquipmentListResponse, EquipmentStatistics,
  FailureCode, WorkOrderFilters, WorkOrderListResponse, WorkOrderStatistics, WorkOrder,
  CalibrationPlanFilters, CalibrationPlanListResponse,
  CalibrationRecordFilters, CalibrationRecordListResponse,
  SparePartFilters, SparePartListResponse, SparePart, StockWarning,
  MaintenancePlanFilters, MaintenancePlanListResponse, MaintenancePlan,
  InspectionTemplateFilters, InspectionTemplateListResponse, InspectionTemplate,
  MaterialRecord,
  ClaimTimeoutConfig, Maintainer, WorkOrderImage,
} from '@/types/equipment'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface FetchEquipmentsParams {
  category_id?: string | null
  location_id?: string | null
  department_id?: string | null
  status?: string
  keyword?: string
  page?: number
  page_size?: number
}

export async function fetchEquipmentsClient(params: FetchEquipmentsParams = {}): Promise<EquipmentListResponse> {
  const searchParams = new URLSearchParams()

  if (params.category_id) searchParams.append('category_id', params.category_id)
  if (params.location_id) searchParams.append('location_id', params.location_id)
  if (params.department_id) searchParams.append('department_id', params.department_id)
  if (params.status) searchParams.append('status', params.status)
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.page && params.page > 0) searchParams.append('page', params.page.toString())
  if (params.page_size && params.page_size > 0) searchParams.append('page_size', params.page_size.toString())

  const queryString = searchParams.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/equipments?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/equipments`

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }

  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

export async function fetchEquipmentStatisticsClient(): Promise<EquipmentStatistics> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/equipments/statistics`)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }

  const result = await response.json()
  return result.data || { total: 0, by_status: {}, by_category: {}, by_location: {} }
}

// ==================== 故障代码 ====================
export async function fetchCategoriesClient(): Promise<EquipmentCategory[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/categories?tree=true`)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const result = await response.json()
  return result.data || []
}

export async function fetchLocationsClient(): Promise<Location[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/locations?tree=true`)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const result = await response.json()
  return result.data || []
}

export async function fetchFailureCodesClient(type: 'symptoms' | 'causes' | 'actions'): Promise<FailureCode[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${type}`)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const result = await response.json()
  return result.data || []
}

// ==================== 维修工单 ====================
export async function fetchWorkOrdersClient(params: WorkOrderFilters = {}): Promise<WorkOrderListResponse> {
  const searchParams = new URLSearchParams()
  if (params.status) searchParams.append('status', params.status)
  if (params.equipment_id) searchParams.append('equipment_id', params.equipment_id)
  if (params.priority) searchParams.append('priority', params.priority)
  if (params.order_type) searchParams.append('order_type', params.order_type)
  if (params.page && params.page > 0) searchParams.append('page', params.page.toString())
  if (params.page_size && params.page_size > 0) searchParams.append('page_size', params.page_size.toString())

  const queryString = searchParams.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/`

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }

  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

export async function fetchWorkOrderStatisticsClient(): Promise<WorkOrderStatistics> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/statistics`)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const result = await response.json()
  return result.data || { total: 0, by_status: {}, by_type: {}, by_priority: {} }
}

export async function fetchWorkOrderByIdClient(id: string): Promise<WorkOrder> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}`)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const result = await response.json()
  return result.data
}

// ==================== 校准计划 ====================
export async function fetchCalibrationPlansClient(params: CalibrationPlanFilters = {}): Promise<CalibrationPlanListResponse> {
  const searchParams = new URLSearchParams()
  if (params.equipment_id) searchParams.append('equipment_id', params.equipment_id)
  if (params.status) searchParams.append('status', params.status)
  if (params.page && params.page > 0) searchParams.append('page', params.page.toString())
  if (params.page_size && params.page_size > 0) searchParams.append('page_size', params.page_size.toString())

  const queryString = searchParams.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans`

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }

  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

// ==================== 校准记录 ====================
export async function fetchCalibrationRecordsClient(params: CalibrationRecordFilters = {}): Promise<CalibrationRecordListResponse> {
  const searchParams = new URLSearchParams()
  if (params.equipment_id) searchParams.append('equipment_id', params.equipment_id)
  if (params.plan_id) searchParams.append('plan_id', params.plan_id)
  if (params.page && params.page > 0) searchParams.append('page', params.page.toString())
  if (params.page_size && params.page_size > 0) searchParams.append('page_size', params.page_size.toString())

  const queryString = searchParams.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/records?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/records`

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }

  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

// ==================== 备件管理 ====================
export async function fetchSparePartsClient(params: SparePartFilters = {}): Promise<SparePartListResponse> {
  const searchParams = new URLSearchParams()
  if (params.category) searchParams.append('category', params.category)
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.is_active !== undefined) searchParams.append('is_active', params.is_active.toString())
  if (params.page && params.page > 0) searchParams.append('page', params.page.toString())
  if (params.page_size && params.page_size > 0) searchParams.append('page_size', params.page_size.toString())

  const queryString = searchParams.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/spare-parts/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/spare-parts/`

  const response = await fetch(url)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

export async function fetchSparePartByIdClient(id: string): Promise<SparePart> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}`)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return result.data
}

export async function fetchStockWarningsClient(): Promise<StockWarning[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/spare-parts/stock/warnings`)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return result.data || []
}

// ==================== 维护计划 ====================
export async function fetchMaintenancePlansClient(params: MaintenancePlanFilters = {}): Promise<MaintenancePlanListResponse> {
  const searchParams = new URLSearchParams()
  if (params.equipment_id) searchParams.append('equipment_id', params.equipment_id)
  if (params.status) searchParams.append('status', params.status)
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.page && params.page > 0) searchParams.append('page', params.page.toString())
  if (params.page_size && params.page_size > 0) searchParams.append('page_size', params.page_size.toString())

  const queryString = searchParams.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/plans/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/plans/`

  const response = await fetch(url)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

export async function fetchOverdueMaintenancePlansClient(days?: number): Promise<MaintenancePlan[]> {
  const params = days ? `?days=${days}` : ''
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/overdue${params}`)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return result.data || []
}

// ==================== 巡检模板 ====================
export async function fetchInspectionTemplatesClient(params: InspectionTemplateFilters = {}): Promise<InspectionTemplateListResponse> {
  const searchParams = new URLSearchParams()
  if (params.equipment_category_id) searchParams.append('equipment_category_id', params.equipment_category_id)
  if (params.is_active !== undefined) searchParams.append('is_active', params.is_active.toString())
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.page && params.page > 0) searchParams.append('page', params.page.toString())
  if (params.page_size && params.page_size > 0) searchParams.append('page_size', params.page_size.toString())

  const queryString = searchParams.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/`

  const response = await fetch(url)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

export async function fetchInspectionTemplateByIdClient(id: string): Promise<InspectionTemplate> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return result.data
}

// ==================== 工单物料 ====================
export async function fetchWorkOrderMaterialsClient(workOrderId: string): Promise<MaterialRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/materials`)
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return result.data || []
}

// ==================== 维修人员 ====================
export async function fetchMaintainersClient(): Promise<Maintainer[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/staff/maintainers`)
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return result.data || []
}

export async function fetchAllUsersClient(): Promise<Maintainer[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/staff/all-users`)
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return result.data || []
}

// ==================== 工单图片 ====================
export async function fetchWorkOrderImagesClient(workOrderId: string): Promise<WorkOrderImage[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/images`)
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return result.data || []
}

// ==================== 超时配置 ====================
export async function fetchClaimTimeoutConfigClient(): Promise<ClaimTimeoutConfig> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/config/claim-timeout`)
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return result.data || { emergency: 15, high: 30, medium: 60, low: 120 }
}

// ==================== 部门列表 ====================
export async function fetchDepartmentsClient(): Promise<import('@/types/equipment').DepartmentOption[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/departments`)
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return result.data || []
}
