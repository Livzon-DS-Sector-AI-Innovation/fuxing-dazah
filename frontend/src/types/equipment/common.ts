// ==================== 工单图片 ====================
export interface WorkOrderImage {
  id: string
  work_order_id: string
  file_name: string
  file_size: number | null
  uploaded_at: string
}

// ==================== 抢单超时配置 ====================
export interface ClaimTimeoutConfig {
  emergency: number
  high: number
  medium: number
  low: number
}

export interface UpdateClaimTimeoutInput {
  emergency?: number
  high?: number
  medium?: number
  low?: number
}

// ==================== 维修人员 ====================
export interface Maintainer {
  user_id: string
  name: string
  employee_no: string
  department_id: string
}

// ==================== 部门（供下拉选择） ====================
export interface DepartmentOption {
  id: string
  name: string
  leader_name: string | null
  leader_user_id: string | null
  leader_id: string | null
}

// ==================== 维护计划自动创建配置 ====================
export interface AdvanceDaysConfig {
  advance_days: number
  auto_execute: boolean
}
