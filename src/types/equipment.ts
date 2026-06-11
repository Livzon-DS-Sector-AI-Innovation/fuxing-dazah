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
export type EquipmentImportance = '高' | '中' | '低'

export interface Equipment {
  id: string
  equipment_no: string
  name: string
  category_ids: string[]
  category_names?: string | null
  location_id: string
  status: EquipmentStatus
  importance: EquipmentImportance
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
  department_id: string | null
  department_name: string | null
  responsible_person_id: string | null
  responsible_person_name: string | null
  category?: EquipmentCategory
  location?: Location
}

export interface CreateEquipmentInput {
  name: string
  equipment_no: string
  category_ids: string[]
  location_id: string
  status?: EquipmentStatus
  importance?: EquipmentImportance
  model?: string
  specification?: string
  manufacturer?: string
  supplier?: string
  production_date?: string
  commissioning_date?: string
  description?: string
  department_id?: string
  responsible_person_id?: string
}

export interface UpdateEquipmentInput {
  name?: string
  category_ids?: string[]
  location_id?: string
  status?: EquipmentStatus
  importance?: EquipmentImportance
  model?: string
  specification?: string
  manufacturer?: string
  supplier?: string
  production_date?: string
  commissioning_date?: string
  description?: string
  department_id?: string
  responsible_person_id?: string | null
}

// 列表和筛选
export interface EquipmentFilters {
  category_id?: string
  location_id?: string
  department_id?: string
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
export type WorkOrderType = '故障维修' | '计划维护' | '巡检' | '校准' | '异常处理' | '日常维护'
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

// ==================== 备件管理 ====================
export interface SparePart {
  id: string
  code: string
  name: string
  specification: string | null
  unit: string
  category: string | null
  default_supplier: string | null
  unit_price: number | null
  min_qty: number
  current_qty: number
  is_active: boolean
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
}

export interface CreateSparePartInput {
  code: string
  name: string
  specification?: string
  unit: string
  category?: string
  default_supplier?: string
  unit_price?: number
  is_active?: boolean
}

export interface UpdateSparePartInput {
  code?: string
  name?: string
  specification?: string
  unit?: string
  category?: string
  default_supplier?: string
  unit_price?: number
  is_active?: boolean
}

export interface SparePartFilters {
  category?: string
  keyword?: string
  is_active?: boolean
  page?: number
  page_size?: number
}

export interface SparePartListResponse {
  items: SparePart[]
  total: number
  page: number
  page_size: number
}

export interface StockInboundInput {
  quantity: number
  warehouse_location?: string
  remark?: string
}

export interface StockAdjustInput {
  new_qty: number
  remark?: string
}

export interface StockWarning {
  spare_part_id: string
  code: string
  name: string
  current_qty: number
  min_qty: number
}

// ==================== 维护计划 ====================
export type MaintenancePlanType = '预防性维护' | '预测性维护'
export type MaintenancePlanStatus = '启用' | '停用' | '已完成'
export type FrequencyUnit = '天' | '周' | '月' | '年'

export interface MaintenancePlan {
  id: string
  equipment_id: string
  plan_name: string
  plan_type: MaintenancePlanType
  frequency: number
  frequency_unit: FrequencyUnit
  last_maintenance_date: string | null
  next_maintenance_date: string | null
  responsible_person_id: string | null
  maintenance_content: string | null
  status: MaintenancePlanStatus
  remark: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  equipment_name?: string
  equipment_no?: string
  responsible_person_name?: string
}

export interface CreateMaintenancePlanInput {
  equipment_id: string
  plan_name: string
  plan_type?: MaintenancePlanType
  frequency: number
  frequency_unit: FrequencyUnit
  last_maintenance_date?: string
  responsible_person_id?: string
  maintenance_content?: string
  remark?: string
}

export interface UpdateMaintenancePlanInput {
  plan_name?: string
  plan_type?: MaintenancePlanType
  frequency?: number
  frequency_unit?: FrequencyUnit
  last_maintenance_date?: string
  responsible_person_id?: string
  maintenance_content?: string
  status?: MaintenancePlanStatus
  remark?: string
}

export interface MaintenancePlanFilters {
  equipment_id?: string
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

// ==================== 巡检模板 ====================
export interface InspectionTemplate {
  id: string
  name: string
  description: string | null
  equipment_category_id: string | null
  is_active: boolean
  items_count: number
  created_at: string
  updated_at: string
  created_by: string | null
  updated_by: string | null
  equipment_category_name?: string
  items?: InspectionTemplateItem[]
}

export interface InspectionTemplateItem {
  id: string
  template_id: string
  item_name: string
  item_description: string | null
  expected_result: string | null
  check_method: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface CreateInspectionTemplateInput {
  name: string
  description?: string
  equipment_category_id?: string
  is_active?: boolean
  items?: CreateInspectionTemplateItemInput[]
}

export interface UpdateInspectionTemplateInput {
  name?: string
  description?: string
  equipment_category_id?: string
  is_active?: boolean
}

export interface CreateInspectionTemplateItemInput {
  item_name: string
  item_description?: string
  expected_result?: string
  check_method?: string
  sort_order?: number
}

export interface UpdateInspectionTemplateItemInput {
  item_name?: string
  item_description?: string
  expected_result?: string
  check_method?: string
  sort_order?: number
}

export interface InspectionTemplateFilters {
  equipment_category_id?: string
  is_active?: boolean
  keyword?: string
  page?: number
  page_size?: number
}

export interface InspectionTemplateListResponse {
  items: InspectionTemplate[]
  total: number
  page: number
  page_size: number
}

export interface InspectionRecordItem {
  item_id: string
  result: string
  actual_value?: string
  remark?: string
}

export interface InspectionCompleteInput {
  records: InspectionRecordItem[]
}

// ==================== 物料领用 ====================
export interface MaterialConsumeItem {
  spare_part_id: string
  quantity: number
  remark?: string
}

export interface MaterialConsumeInput {
  items: MaterialConsumeItem[]
}

export interface MaterialRecord {
  id: string
  work_order_id: string
  spare_part_id: string
  quantity: number
  remark: string | null
  created_at: string
  created_by: string | null
  spare_part_name?: string
  spare_part_code?: string
  spare_part_unit?: string
}

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
