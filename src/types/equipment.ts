// 设备分类
export interface EquipmentCategory {
  id: string
  name: string
  code: string
  parent_id: string | null
  description: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  children?: EquipmentCategory[]
}

export interface CreateCategoryInput {
  name: string
  code: string
  parent_id?: string
  description?: string
}

export interface UpdateCategoryInput {
  name?: string
  code?: string
  parent_id?: string
  description?: string
}

// 位置管理
export interface Location {
  id: string
  name: string
  code: string
  parent_id: string | null
  description: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  children?: Location[]
}

export interface CreateLocationInput {
  name: string
  code: string
  parent_id?: string
  description?: string
}

export interface UpdateLocationInput {
  name?: string
  code?: string
  parent_id?: string
  description?: string
}

// 设备管理
export type EquipmentStatus = '在用' | '备用' | '维修中' | '停用' | '报废'

export interface Equipment {
  id: string
  equipment_no: string
  name: string
  category_id: string
  location_id: string
  status: EquipmentStatus
  model: string | null
  specification: string | null
  manufacturer: string | null
  supplier: string | null
  production_date: string | null
  commissioning_date: string | null
  description: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  category?: EquipmentCategory
  location?: Location
}

export interface CreateEquipmentInput {
  name: string
  category_id: string
  location_id: string
  status?: EquipmentStatus
  model?: string
  specification?: string
  manufacturer?: string
  supplier?: string
  production_date?: string
  commissioning_date?: string
  description?: string
}

export interface UpdateEquipmentInput {
  name?: string
  category_id?: string
  location_id?: string
  status?: EquipmentStatus
  model?: string
  specification?: string
  manufacturer?: string
  supplier?: string
  production_date?: string
  commissioning_date?: string
  description?: string
}

// 列表和筛选
export interface EquipmentFilters {
  category_id?: string
  location_id?: string
  status?: EquipmentStatus
  keyword?: string
  page?: number
  page_size?: number
}

export interface EquipmentListResponse {
  items: Equipment[]
  total: number
  page: number
  page_size: number
}

// 统计
export interface EquipmentStatistics {
  total: number
  by_status: Record<EquipmentStatus, number>
  by_category: Record<string, number>
  by_location: Record<string, number>
}

// ==================== 故障代码 ====================
export type FailureCodeType = 'symptom' | 'cause' | 'action'

export interface FailureCode {
  id: string
  code: string
  name: string
  description: string | null
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
}

export interface CreateFailureCodeInput {
  code: string
  name: string
  description?: string
  sort_order?: number
  is_active?: boolean
}

export interface UpdateFailureCodeInput {
  code?: string
  name?: string
  description?: string
  sort_order?: number
  is_active?: boolean
}

// ==================== 维修工单 ====================
export type WorkOrderType = '故障维修' | '校准'
export type WorkOrderPriority = '紧急' | '高' | '中' | '低'
export type WorkOrderStatus = '待处理' | '已指派' | '维修中' | '待验收' | '已完成' | '已关闭'
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
  equipment_name?: string
  equipment_no?: string
  symptom_name?: string
  cause_name?: string
  action_name?: string
  reporter_name?: string
  assignee_name?: string
  verifier_name?: string
}

export interface CreateWorkOrderInput {
  equipment_id: string
  order_type?: WorkOrderType
  priority?: WorkOrderPriority
  fault_symptom_id?: string
  fault_cause_id?: string
  fault_action_id?: string
  fault_description?: string
}

export interface AssignWorkOrderInput {
  assignee_id: string
}

export interface CompleteWorkOrderInput {
  repair_detail: string
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

// ==================== 校准管理 ====================
export type CalibrationType = '内部校准' | '外部检定'
export type CalibrationResult = '合格' | '不合格'
export type CalibrationPlanStatus = '启用' | '停用'

export interface CalibrationPlan {
  id: string
  equipment_id: string
  calibration_type: CalibrationType
  cycle_months: number
  last_calibration_date: string | null
  next_calibration_date: string | null
  responsible_person_id: string | null
  status: CalibrationPlanStatus
  remark: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  equipment_name?: string
  equipment_no?: string
  responsible_person_name?: string
}

export interface CreateCalibrationPlanInput {
  equipment_id: string
  calibration_type: CalibrationType
  cycle_months: number
  last_calibration_date?: string
  responsible_person_id?: string
  remark?: string
}

export interface UpdateCalibrationPlanInput {
  calibration_type?: CalibrationType
  cycle_months?: number
  last_calibration_date?: string
  responsible_person_id?: string
  status?: CalibrationPlanStatus
  remark?: string
}

export interface CalibrationPlanFilters {
  equipment_id?: string
  status?: CalibrationPlanStatus
  page?: number
  page_size?: number
}

export interface CalibrationPlanListResponse {
  items: CalibrationPlan[]
  total: number
  page: number
  page_size: number
}

export interface CalibrationRecord {
  id: string
  calibration_plan_id: string
  equipment_id: string
  calibration_date: string
  calibration_type: CalibrationType
  result: CalibrationResult
  certificate_no: string | null
  calibrated_by: string | null
  next_due_date: string
  remark: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  equipment_name?: string
  equipment_no?: string
}

export interface CreateCalibrationRecordInput {
  calibration_plan_id: string
  calibration_date: string
  calibration_type: CalibrationType
  result: CalibrationResult
  certificate_no?: string
  calibrated_by?: string
  remark?: string
}

export interface CalibrationRecordFilters {
  equipment_id?: string
  plan_id?: string
  page?: number
  page_size?: number
}

export interface CalibrationRecordListResponse {
  items: CalibrationRecord[]
  total: number
  page: number
  page_size: number
}
