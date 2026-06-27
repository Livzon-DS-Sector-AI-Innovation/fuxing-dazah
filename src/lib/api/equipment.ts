import {
  EquipmentCategory, Location, EquipmentFilters, EquipmentListResponse, EquipmentStatistics,
  FailureCode, WorkOrderFilters, WorkOrderListResponse, WorkOrderStatistics, WorkOrder,
  CalibrationPlanFilters, CalibrationPlanListResponse, CalibrationPlan,
  CalibrationRecordFilters, CalibrationRecordListResponse, CalibrationRecord,
  SparePartFilters, SparePartListResponse, SparePart, StockWarning,
  MaintenancePlanFilters, MaintenancePlanListResponse, MaintenancePlan,
  InspectionTemplateFilters, InspectionTemplateListResponse, InspectionTemplate,
  MaterialRecord,
} from '@/types/equipment'
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

// ═══════════════════════════════════════════════════════════
//  设备分类
// ═══════════════════════════════════════════════════════════
export async function fetchCategories(): Promise<EquipmentCategory[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/categories`)
}

export async function fetchCategoryTree(): Promise<EquipmentCategory[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/categories?tree=true`)
}

// ═══════════════════════════════════════════════════════════
//  位置管理
// ═══════════════════════════════════════════════════════════
export async function fetchLocations(): Promise<Location[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/locations`)
}

export async function fetchLocationTree(): Promise<Location[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/locations?tree=true`)
}

// ═══════════════════════════════════════════════════════════
//  设备管理
// ═══════════════════════════════════════════════════════════
export async function fetchEquipments(filters: EquipmentFilters = {}): Promise<EquipmentListResponse> {
  const params = new URLSearchParams()
  if (filters.category_id) params.append('category_id', filters.category_id)
  if (filters.location_id) params.append('location_id', filters.location_id)
  if (filters.department_id) params.append('department_id', filters.department_id)
  if (filters.status) params.append('status', filters.status)
  if (filters.keyword) params.append('keyword', filters.keyword)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/equipments?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/equipments`

  return apiFetchPaginated(url)
}

export async function fetchEquipmentStatistics(): Promise<EquipmentStatistics> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/equipments/statistics`)
}

// ═══════════════════════════════════════════════════════════
//  故障代码
// ═══════════════════════════════════════════════════════════
export async function fetchFailureCodes(type: 'symptoms' | 'causes' | 'actions'): Promise<FailureCode[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${type}`)
}

// ═══════════════════════════════════════════════════════════
//  维修工单
// ═══════════════════════════════════════════════════════════
export async function fetchWorkOrders(filters: WorkOrderFilters = {}): Promise<WorkOrderListResponse> {
  const params = new URLSearchParams()
  if (filters.status) params.append('status', filters.status)
  if (filters.equipment_id) params.append('equipment_id', filters.equipment_id)
  if (filters.priority) params.append('priority', filters.priority)
  if (filters.order_type) params.append('order_type', filters.order_type)
  if (filters.exclude_status) params.append('exclude_status', filters.exclude_status)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/`

  return apiFetchPaginated(url)
}

export async function fetchWorkOrderStatistics(exclude_status?: string): Promise<WorkOrderStatistics> {
  const params = new URLSearchParams()
  if (exclude_status) params.append('exclude_status', exclude_status)
  const qs = params.toString()
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/statistics${qs ? `?${qs}` : ''}`)
}

export async function fetchWorkOrderById(id: string): Promise<WorkOrder> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}`)
}

// ═══════════════════════════════════════════════════════════
//  校准计划
// ═══════════════════════════════════════════════════════════
export async function fetchCalibrationPlans(filters: CalibrationPlanFilters = {}): Promise<CalibrationPlanListResponse> {
  const params = new URLSearchParams()
  if (filters.equipment_id) params.append('equipment_id', filters.equipment_id)
  if (filters.status) params.append('status', filters.status)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans`

  return apiFetchPaginated(url)
}

export async function fetchCalibrationPlanById(id: string): Promise<CalibrationPlan> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans/${id}`)
}

// ═══════════════════════════════════════════════════════════
//  校准记录
// ═══════════════════════════════════════════════════════════
export async function fetchCalibrationRecords(filters: CalibrationRecordFilters = {}): Promise<CalibrationRecordListResponse> {
  const params = new URLSearchParams()
  if (filters.equipment_id) params.append('equipment_id', filters.equipment_id)
  if (filters.plan_id) params.append('plan_id', filters.plan_id)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/records?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/calibration/records`

  return apiFetchPaginated(url)
}

// ═══════════════════════════════════════════════════════════
//  备件管理
// ═══════════════════════════════════════════════════════════
export async function fetchSpareParts(filters: SparePartFilters = {}): Promise<SparePartListResponse> {
  const params = new URLSearchParams()
  if (filters.category) params.append('category', filters.category)
  if (filters.keyword) params.append('keyword', filters.keyword)
  if (filters.is_active !== undefined) params.append('is_active', filters.is_active.toString())
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/spare-parts/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/spare-parts/`

  return apiFetchPaginated(url)
}

export async function fetchSparePartById(id: string): Promise<SparePart> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}`)
}

export async function fetchStockWarnings(): Promise<StockWarning[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/spare-parts/stock/warnings`)
}

export async function fetchSparePartStock(id: string): Promise<{ current_qty: number; min_qty: number }> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}/stock`)
}

// ═══════════════════════════════════════════════════════════
//  维护计划
// ═══════════════════════════════════════════════════════════
export async function fetchMaintenancePlans(filters: MaintenancePlanFilters = {}): Promise<MaintenancePlanListResponse> {
  const params = new URLSearchParams()
  if (filters.equipment_id) params.append('equipment_id', filters.equipment_id)
  if (filters.category_id) params.append('category_id', filters.category_id)
  if (filters.status) params.append('status', filters.status)
  if (filters.keyword) params.append('keyword', filters.keyword)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/plans/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/plans/`

  return apiFetchPaginated(url)
}

export async function fetchMaintenancePlanById(id: string): Promise<MaintenancePlan> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/${id}`)
}

export async function fetchOverdueMaintenancePlans(days?: number): Promise<MaintenancePlan[]> {
  const params = days ? `?days=${days}` : ''
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/overdue${params}`)
}

// ═══════════════════════════════════════════════════════════
//  巡检模板
// ═══════════════════════════════════════════════════════════
export async function fetchInspectionTemplates(filters: InspectionTemplateFilters = {}): Promise<InspectionTemplateListResponse> {
  const params = new URLSearchParams()
  if (filters.equipment_category_id) params.append('equipment_category_id', filters.equipment_category_id)
  if (filters.is_active !== undefined) params.append('is_active', filters.is_active.toString())
  if (filters.keyword) params.append('keyword', filters.keyword)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/`

  return apiFetchPaginated(url)
}

export async function fetchInspectionTemplateById(id: string): Promise<InspectionTemplate> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`)
}

// ═══════════════════════════════════════════════════════════
//  工单物料
// ═══════════════════════════════════════════════════════════
export async function fetchWorkOrderMaterials(workOrderId: string): Promise<MaterialRecord[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/materials`)
}

// ═══════════════════════════════════════════════════════════
//  部门列表
// ═══════════════════════════════════════════════════════════
export interface DepartmentOption {
  id: string
  name: string
  leader_name: string | null
  leader_user_id: string | null
  leader_id: string | null
}

export async function fetchDepartments(): Promise<DepartmentOption[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/departments`)
}
