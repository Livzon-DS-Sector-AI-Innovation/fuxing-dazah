import type { WorkOrderImage } from './common'

// ==================== 维修工单 ====================
export type WorkOrderType = '故障维修' | '计划维护' | '校准' | '异常处理' | '日常维护'
export type WorkOrderPriority = '紧急' | '高' | '中' | '低'
export type WorkOrderStatus = '待处理' | '执行中' | '待验收' | '已完成' | '已关闭'
export type VerificationResult = '合格' | '不合格'

export interface WorkOrder {
  id: string
  work_order_no: string
  equipment_id: string
  order_type: WorkOrderType
  priority: WorkOrderPriority
  status: WorkOrderStatus
  fault_symptom_id: string | null
  fault_cause_id: string | null
  fault_action_id: string | null
  fault_description: string | null
  reporter_id: string
  assignee_id: string | null
  responsible_person_id: string | null
  responsible_person_name?: string
  verified_by: string | null
  reported_at: string
  assigned_at: string | null
  started_at: string | null
  completed_at: string | null
  verified_at: string | null
  verification_result: VerificationResult | null
  verification_remark: string | null
  repair_detail: string | null
  actual_duration: number | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  maintenance_plan_id: string | null
  planned_start_date: string | null
  checklist_template_id: string | null
  equipment_name?: string
  equipment_no?: string
  symptom_name?: string
  cause_name?: string
  action_name?: string
  reporter_name?: string
  assignee_name?: string
  verifier_name?: string
  images?: WorkOrderImage[]
}

export interface CreateWorkOrderInput {
  equipment_id: string
  order_type?: WorkOrderType
  priority?: WorkOrderPriority
  fault_symptom_id?: string
  fault_cause_id?: string
  fault_action_id?: string
  fault_description?: string
  maintenance_plan_id?: string
  planned_start_date?: string
  checklist_template_id?: string
  responsible_person_id: string
}

export interface UpdateWorkOrderInput {
  equipment_id?: string
  order_type?: WorkOrderType
  priority?: WorkOrderPriority
  status?: WorkOrderStatus
  fault_symptom_id?: string
  fault_cause_id?: string
  fault_action_id?: string
  fault_description?: string
  planned_start_date?: string
  responsible_person_id?: string
}

export interface AssignWorkOrderInput {
  assignee_id: string
}

export interface CompleteWorkOrderInput {
  repair_detail: string
  consumed_parts?: { spare_part_id: string; quantity: number }[]
}

export interface VerifyWorkOrderInput {
  result: VerificationResult
  remark?: string
}

export interface WorkOrderFilters {
  status?: WorkOrderStatus
  equipment_id?: string
  priority?: WorkOrderPriority
  order_type?: WorkOrderType
  exclude_status?: string
  page?: number
  page_size?: number
}

export interface WorkOrderListResponse {
  items: WorkOrder[]
  total: number
  page: number
  page_size: number
}

export interface WorkOrderStatistics {
  total: number
  by_status: Record<WorkOrderStatus, number>
  by_type: Record<WorkOrderType, number>
  by_priority: Record<WorkOrderPriority, number>
}
