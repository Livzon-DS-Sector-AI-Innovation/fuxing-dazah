import {
  InspectionRouteFilters, InspectionRouteListResponse, InspectionRoute, InspectionRouteDetail,
  InspectionTaskFilters, InspectionTaskListResponse, InspectionTask,
  InspectionHistoryFilters, InspectionHistoryListResponse, InspectionTaskDetail,
  InspectionPhoto, RouteLocationsBatch, RouteLocation,
} from '@/types/inspection'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const INSPECTION_BASE = `${API_BASE_URL}/api/v1/equipment/inspection`

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const data = await response.json()
  return data.data
}

// ==================== 巡检路线 ====================
export async function fetchInspectionRoutes(filters: InspectionRouteFilters = {}): Promise<InspectionRouteListResponse> {
  const params = new URLSearchParams()
  if (filters.is_active !== undefined) params.append('is_active', filters.is_active.toString())
  if (filters.location_id) params.append('location_id', filters.location_id)
  if (filters.period_type) params.append('period_type', filters.period_type)
  if (filters.keyword) params.append('keyword', filters.keyword)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())
  const qs = params.toString()
  const url = qs ? `${INSPECTION_BASE}/routes?${qs}` : `${INSPECTION_BASE}/routes`
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' } })
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return { items: result.data || [], total: result.meta?.total || 0, page: result.meta?.page || 1, page_size: result.meta?.page_size || 20 }
}

export async function fetchInspectionRouteById(id: string): Promise<InspectionRouteDetail> {
  return apiFetch(`${INSPECTION_BASE}/routes/${id}`)
}

export async function fetchInspectionTemplatesClient(params: { is_active?: boolean; keyword?: string; page?: number; page_size?: number } = {}) {
  const searchParams = new URLSearchParams()
  if (params.is_active !== undefined) searchParams.append('is_active', params.is_active.toString())
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.page) searchParams.append('page', params.page.toString())
  if (params.page_size) searchParams.append('page_size', params.page_size.toString())
  const qs = searchParams.toString()
  const url = qs ? `${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/?${qs}` : `${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/`
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' } })
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return { items: result.data || [], total: result.meta?.total || 0, page: result.meta?.page || 1, page_size: result.meta?.page_size || 20 }
}

export async function fetchInspectionTemplateByIdClient(id: string) {
  const response = await fetch(`${API_BASE_URL}/api/v1/equipment/maintenance/inspection-templates/${id}`, { headers: { 'Content-Type': 'application/json' } })
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return result.data
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
  const url = qs ? `${INSPECTION_BASE}/tasks?${qs}` : `${INSPECTION_BASE}/tasks`
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' } })
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return { items: result.data || [], total: result.meta?.total || 0, page: result.meta?.page || 1, page_size: result.meta?.page_size || 20 }
}

export async function fetchInspectionTaskById(taskId: string): Promise<InspectionTask> {
  return apiFetch<InspectionTask>(`${INSPECTION_BASE}/tasks/${taskId}`)
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
  const url = qs ? `${INSPECTION_BASE}/history?${qs}` : `${INSPECTION_BASE}/history`
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' } })
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return { items: result.data || [], total: result.meta?.total || 0, page: result.meta?.page || 1, page_size: result.meta?.page_size || 20 }
}

export async function fetchInspectionHistoryDetail(taskId: string): Promise<InspectionTaskDetail> {
  return apiFetch(`${INSPECTION_BASE}/history/${taskId}`)
}

// ==================== 照片 ====================
export async function fetchInspectionTaskPhotos(taskId: string): Promise<InspectionPhoto[]> {
  return apiFetch(`${INSPECTION_BASE}/tasks/${taskId}/photos`)
}

export function getInspectionPhotoUrl(photoId: string): string {
  return `${INSPECTION_BASE}/photos/${photoId}/file`
}

// ==================== 路线地点配置 ====================
export async function fetchRouteLocations(routeId: string): Promise<InspectionRouteDetail> {
  return apiFetch(`${INSPECTION_BASE}/routes/${routeId}`)
}

export async function setRouteLocations(routeId: string, data: RouteLocationsBatch): Promise<RouteLocation[]> {
  const response = await fetch(`${INSPECTION_BASE}/routes/${routeId}/locations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!response.ok) throw new Error(`保存失败: ${response.status}`)
  const result = await response.json()
  return result.data || []
}

// ==================== 设备列表 ====================
export async function fetchEquipmentsClient(params: { page?: number; page_size?: number; keyword?: string } = {}) {
  const searchParams = new URLSearchParams()
  if (params.keyword) searchParams.append('keyword', params.keyword)
  if (params.page) searchParams.append('page', params.page.toString())
  if (params.page_size) searchParams.append('page_size', params.page_size.toString())
  const qs = searchParams.toString()
  const url = qs ? `${API_BASE_URL}/api/v1/equipment/equipments?${qs}` : `${API_BASE_URL}/api/v1/equipment/equipments`
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' } })
  if (!response.ok) throw new Error(`请求失败: ${response.status}`)
  const result = await response.json()
  return { items: result.data || [], total: result.meta?.total || 0, page: result.meta?.page || 1, page_size: result.meta?.page_size || 20 }
}
