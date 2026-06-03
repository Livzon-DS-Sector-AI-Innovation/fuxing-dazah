import {
  EquipmentCategory, Location, EquipmentFilters, EquipmentListResponse, EquipmentStatistics,
  FailureCode, WorkOrderFilters, WorkOrderListResponse, WorkOrderStatistics, WorkOrder,
  CalibrationPlanFilters, CalibrationPlanListResponse, CalibrationPlan,
  CalibrationRecordFilters, CalibrationRecordListResponse, CalibrationRecord,
} from '@/types/equipment'

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000'

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
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
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const data = await response.json()
  return data.data
}

// 处理带分页的响应
async function apiFetchPaginated(url: string, options?: RequestInit): Promise<EquipmentListResponse> {
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
    throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  }
  const result = await response.json()
  // 后端返回格式: { code, message, data: [...], meta: { page, page_size, total } }
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

// 设备分类
export async function fetchCategories(): Promise<EquipmentCategory[]> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/categories`)
}

export async function fetchCategoryTree(): Promise<EquipmentCategory[]> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/categories?tree=true`)
}

// 位置管理
export async function fetchLocations(): Promise<Location[]> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/locations`)
}

export async function fetchLocationTree(): Promise<Location[]> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/locations?tree=true`)
}

// 设备管理
export async function fetchEquipments(filters: EquipmentFilters = {}): Promise<EquipmentListResponse> {
  const params = new URLSearchParams()
  if (filters.category_id) params.append('category_id', filters.category_id)
  if (filters.location_id) params.append('location_id', filters.location_id)
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
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/equipments/statistics`)
}

// ==================== 故障代码 ====================
export async function fetchFailureCodes(type: 'symptoms' | 'causes' | 'actions'): Promise<FailureCode[]> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/failure-codes/${type}`)
}

// ==================== 维修工单 ====================
export async function fetchWorkOrders(filters: WorkOrderFilters = {}): Promise<WorkOrderListResponse> {
  const params = new URLSearchParams()
  if (filters.status) params.append('status', filters.status)
  if (filters.equipment_id) params.append('equipment_id', filters.equipment_id)
  if (filters.priority) params.append('priority', filters.priority)
  if (filters.order_type) params.append('order_type', filters.order_type)
  if (filters.page) params.append('page', filters.page.toString())
  if (filters.page_size) params.append('page_size', filters.page_size.toString())

  const queryString = params.toString()
  const url = queryString
    ? `${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/?${queryString}`
    : `${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/`

  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

export async function fetchWorkOrderStatistics(): Promise<WorkOrderStatistics> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/statistics`)
}

export async function fetchWorkOrderById(id: string): Promise<WorkOrder> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/work-orders/${id}`)
}

// ==================== 校准计划 ====================
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

  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}

export async function fetchCalibrationPlanById(id: string): Promise<CalibrationPlan> {
  return apiFetch(`${API_BASE_URL}/api/v1/equipment/maintenance/calibration/plans/${id}`)
}

// ==================== 校准记录 ====================
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

  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) throw new Error(`请求失败: ${response.status} ${response.statusText}`)
  const result = await response.json()
  return {
    items: result.data || [],
    total: result.meta?.total || 0,
    page: result.meta?.page || 1,
    page_size: result.meta?.page_size || 20,
  }
}
