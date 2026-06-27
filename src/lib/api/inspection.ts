import {
  InspectionRouteFilters, InspectionRouteListResponse, InspectionRouteDetail,
  InspectionTaskFilters, InspectionTaskListResponse, InspectionTask,
  InspectionHistoryFilters, InspectionHistoryListResponse, InspectionTaskDetail,
  InspectionPhoto, RouteLocationsBatch, RouteLocation,
  InspectionRouteSchedule,
} from '@/types/inspection'
import { apiGet, apiPost, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const INSPECTION_BASE = `${API_BASE_URL}/api/v1/equipment/inspection`

// ==================== 巡检路线 ====================
export async function fetchInspectionRoutes(filters: InspectionRouteFilters = {}): Promise<InspectionRouteListResponse> {
  const params = new URLSearchParams()
  if (filters.is_active !== undefined) params.append('is_active', filters.is_active.toString())
  if (filters.location_id) params.append('location_id', filters.location_id)
  if (filters.keyword) params.append('keyword', filters.keyword)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())
  const qs = params.toString()
  return apiFetchPaginated(`${INSPECTION_BASE}/routes${qs ? `?${qs}` : ''}`)
}

export async function fetchInspectionRouteById(id: string): Promise<InspectionRouteDetail> {
  return apiGet(`${INSPECTION_BASE}/routes/${id}`)
}

// ==================== 巡检模板 ====================
export async function fetchInspectionTemplatesClient(params: { is_active?: boolean; keyword?: string; page?: number; page_size?: number } = {}) {
  const searchParams = new URLSearchParams()
  if (params.is_active !== undefined) searchParams.append('is_active', params.is_active.toString())
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.page) searchParams.append('page', params.page.toString())
  if (params.page_size) searchParams.append('page_size', params.page_size.toString())
  const qs = searchParams.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${qs ? `?${qs}` : ''}`)
}

export async function fetchInspectionTemplateByIdClient(id: string): Promise<any> {
  return apiGet(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`)
}

// ==================== 巡检任务 ====================
export async function fetchInspectionTasks(filters: InspectionTaskFilters = {}): Promise<InspectionTaskListResponse> {
  const params = new URLSearchParams()
  if (filters.status) params.append('status', filters.status)
  if (filters.exclude_status) params.append('exclude_status', filters.exclude_status)
  if (filters.route_id) params.append('route_id', filters.route_id)
  if (filters.assigned_to) params.append('assigned_to', filters.assigned_to)
  if (filters.equipment_id) params.append('equipment_id', filters.equipment_id)
  if (filters.planned_time_from) params.append('planned_time_from', filters.planned_time_from)
  if (filters.planned_time_to) params.append('planned_time_to', filters.planned_time_to)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())
  const qs = params.toString()
  return apiFetchPaginated(`${INSPECTION_BASE}/tasks${qs ? `?${qs}` : ''}`)
}

export async function fetchInspectionTaskById(taskId: string): Promise<InspectionTask> {
  return apiGet(`${INSPECTION_BASE}/tasks/${taskId}`)
}

// ==================== 巡检历史 ====================
export async function fetchInspectionHistory(filters: InspectionHistoryFilters = {}): Promise<InspectionHistoryListResponse> {
  const params = new URLSearchParams()
  if (filters.date_from) params.append('date_from', filters.date_from)
  if (filters.date_to) params.append('date_to', filters.date_to)
  if (filters.equipment_id) params.append('equipment_id', filters.equipment_id)
  if (filters.route_id) params.append('route_id', filters.route_id)
  if (filters.result) params.append('result', filters.result)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())
  const qs = params.toString()
  return apiFetchPaginated(`${INSPECTION_BASE}/history${qs ? `?${qs}` : ''}`)
}

export async function fetchInspectionHistoryDetail(taskId: string): Promise<InspectionTaskDetail> {
  return apiGet(`${INSPECTION_BASE}/history/${taskId}`)
}

// ==================== 照片 ====================
export async function fetchInspectionTaskPhotos(taskId: string): Promise<InspectionPhoto[]> {
  return apiGet(`${INSPECTION_BASE}/tasks/${taskId}/photos`)
}

export function getInspectionPhotoUrl(photoId: string): string {
  return `${INSPECTION_BASE}/photos/${photoId}/file`
}

// ==================== 路线地点配置 ====================
export function fetchRouteLocations(routeId: string): Promise<InspectionRouteDetail> {
  return apiGet(`${INSPECTION_BASE}/routes/${routeId}`)
}

export async function setRouteLocations(routeId: string, data: RouteLocationsBatch): Promise<RouteLocation[]> {
  return apiPost(`${INSPECTION_BASE}/routes/${routeId}/locations`, data)
}

// ==================== 路线定时任务 ====================
export async function fetchRouteSchedules(routeId: string): Promise<InspectionRouteSchedule[]> {
  return apiGet(`${INSPECTION_BASE}/routes/${routeId}/schedules`)
}

// ==================== 设备列表 ====================
export async function fetchEquipmentsClient(params: { page?: number; page_size?: number; keyword?: string } = {}) {
  const searchParams = new URLSearchParams()
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.page) searchParams.append('page', params.page.toString())
  if (params.page_size) searchParams.append('page_size', params.page_size.toString())
  const qs = searchParams.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/equipment/equipments${qs ? `?${qs}` : ''}`)
}
