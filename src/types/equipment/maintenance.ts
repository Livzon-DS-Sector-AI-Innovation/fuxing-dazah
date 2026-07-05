// ==================== 维护计划 ====================
export type MaintenancePlanType = '预防性维护' | '预测性维护'
export type MaintenancePlanStatus = '启用' | '停用' | '已完成'
export type FrequencyUnit = '天' | '周' | '月' | '年'

export interface MaintenancePlan {
  id: string
  equipment_id: string | null
  category_id: string | null
  category_name?: string | null
  plan_name: string
  plan_type: MaintenancePlanType
  frequency: number
  frequency_unit: FrequencyUnit
  last_maintenance_date: string | null
  next_maintenance_date: string | null
  executor_id: string | null
  executor_name?: string | null
  maintenance_content: string | null
  status: MaintenancePlanStatus
  remark: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  equipment_name?: string
  equipment_no?: string
}

export interface CreateMaintenancePlanInput {
  equipment_id?: string
  category_id?: string
  plan_name: string
  plan_type?: MaintenancePlanType
  frequency: number
  frequency_unit: FrequencyUnit
  last_maintenance_date?: string
  executor_id?: string
  maintenance_content?: string
  remark?: string
}

export interface UpdateMaintenancePlanInput {
  plan_name?: string
  plan_type?: MaintenancePlanType
  frequency?: number
  frequency_unit?: FrequencyUnit
  last_maintenance_date?: string
  executor_id?: string
  maintenance_content?: string
  status?: MaintenancePlanStatus
  remark?: string
}

export interface MaintenancePlanFilters {
  equipment_id?: string
  category_id?: string
  status?: MaintenancePlanStatus
  keyword?: string
  page?: number
  page_size?: number
}

export interface MaintenancePlanListResponse {
  items: MaintenancePlan[]
  total: number
  page: number
  page_size: number
}
