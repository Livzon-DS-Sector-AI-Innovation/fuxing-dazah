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
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.append(k, String(v))
  }
  return sp.toString()
}

// ═══════════════════════════════════════════════════════════
//  设备管理
// ═══════════════════════════════════════════════════════════
export async function fetchEquipmentsClient(params: Record<string, string | number | undefined | null> = {}): Promise<EquipmentListResponse> {
  const s = qs(params)
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/equipments${s ? `?${s}` : ''}`)
}

export async function fetchEquipmentStatisticsClient(): Promise<EquipmentStatistics> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/equipments/statistics`)
}

// ═══════════════════════════════════════════════════════════
//  分类 / 位置
// ═══════════════════════════════════════════════════════════
export async function fetchCategoriesClient(): Promise<EquipmentCategory[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/categories?tree=true`)
}

export async function fetchLocationsClient(): Promise<Location[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/locations?tree=true`)
}

// ═══════════════════════════════════════════════════════════
//  故障代码
// ═══════════════════════════════════════════════════════════
export async function fetchFailureCodesClient(type: 'symptoms' | 'causes' | 'actions'): Promise<FailureCode[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${type}`)
}

// ═══════════════════════════════════════════════════════════
//  维修工单
// ═══════════════════════════════════════════════════════════
export async function fetchWorkOrdersClient(params: WorkOrderFilters = {}): Promise<WorkOrderListResponse> {
  const s = qs(params as any)
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${s ? `?${s}` : ''}`)
}

export async function fetchWorkOrderStatisticsClient(exclude_status?: string): Promise<WorkOrderStatistics> {
  const s = exclude_status ? `?exclude_status=${exclude_status}` : ''
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/statistics${s}`)
}

export async function fetchWorkOrderByIdClient(id: string): Promise<WorkOrder> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}`)
}

// ═══════════════════════════════════════════════════════════
//  校准
// ═══════════════════════════════════════════════════════════
export async function fetchCalibrationPlansClient(params: CalibrationPlanFilters = {}): Promise<CalibrationPlanListResponse> {
  const s = qs(params as any)
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans${s ? `?${s}` : ''}`)
}

export async function fetchCalibrationRecordsClient(params: CalibrationRecordFilters = {}): Promise<CalibrationRecordListResponse> {
  const s = qs(params as any)
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/records${s ? `?${s}` : ''}`)
}

// ═══════════════════════════════════════════════════════════
//  备件
// ═══════════════════════════════════════════════════════════
export async function fetchSparePartsClient(params: SparePartFilters = {}): Promise<SparePartListResponse> {
  const s = qs(params as any)
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/spare-parts/${s ? `?${s}` : ''}`)
}

export async function fetchSparePartByIdClient(id: string): Promise<SparePart> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/spare-parts/${id}`)
}

export async function fetchStockWarningsClient(): Promise<StockWarning[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/spare-parts/stock/warnings`)
}

// ═══════════════════════════════════════════════════════════
//  维护计划
// ═══════════════════════════════════════════════════════════
export async function fetchMaintenancePlansClient(params: MaintenancePlanFilters = {}): Promise<MaintenancePlanListResponse> {
  const s = qs(params as any)
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/${s ? `?${s}` : ''}`)
}

export async function fetchOverdueMaintenancePlansClient(days?: number): Promise<MaintenancePlan[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/plans/overdue${days ? `?days=${days}` : ''}`)
}

// ═══════════════════════════════════════════════════════════
//  巡检模板
// ═══════════════════════════════════════════════════════════
export async function fetchInspectionTemplatesClient(params: InspectionTemplateFilters = {}): Promise<InspectionTemplateListResponse> {
  const s = qs(params as any)
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${s ? `?${s}` : ''}`)
}

export async function fetchInspectionTemplateByIdClient(id: string): Promise<InspectionTemplate> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`)
}

// ═══════════════════════════════════════════════════════════
//  工单物料 / 图片 / 维修人员 / 配置 / 部门
// ═══════════════════════════════════════════════════════════
export async function fetchWorkOrderMaterialsClient(workOrderId: string): Promise<MaterialRecord[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/materials`)
}

export async function fetchMaintainersClient(): Promise<Maintainer[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/staff/maintainers`)
}

export async function fetchAllUsersClient(): Promise<Maintainer[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/staff/all-users`)
}

export async function fetchWorkOrderImagesClient(workOrderId: string): Promise<WorkOrderImage[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${workOrderId}/images`)
}

export async function fetchClaimTimeoutConfigClient(): Promise<ClaimTimeoutConfig> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/config/claim-timeout`)
}

export async function fetchDepartmentsClient(): Promise<import('@/types/equipment').DepartmentOption[]> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/departments`)
}
