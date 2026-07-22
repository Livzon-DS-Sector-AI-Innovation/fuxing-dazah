import { HazardType, HazardLevel, HazardCategory, CheckType } from './enums'

export interface HazardIdentification {
  id: string
  hazard_id_no: string
  department: string
  position: string
  production_step: string
  attachment_path?: string
  attachment_original_name?: string
  // Script 1
  specific_activity?: string
  equipment_facilities?: string
  raw_auxiliary_materials?: string
  operation_frequency?: string
  operator_count?: number
  // Script 2
  hazard_type?: string
  possible_accident?: string
  unsafe_behavior?: string
  // Script 3
  l_inherent?: number
  e_inherent?: number
  c_inherent?: number
  d_inherent?: number
  inherent_risk_level?: string
  inherent_risk_label?: string
  // Script 4
  existing_engineering_controls?: string
  existing_management_controls?: string
  existing_ppe?: string
  existing_emergency_measures?: string
  // Script 5
  l_residual?: number
  e_residual?: number
  c_residual?: number
  d_residual?: number
  residual_risk_level?: string
  residual_risk_label?: string
  // Script 6
  needs_recommendation?: string
  recommendation_type?: string
  recommendation_content?: string
  recommendation_priority?: string
  // Script 7
  l_post?: number
  e_post?: number
  c_post?: number
  d_post?: number
  post_risk_level?: string
  post_risk_label?: string
  // Control info
  control_level?: string
  responsible_person?: string
  // Workflow status
  ai_node_progress: string
  ai_error_message?: string
  overall_status: string
  script1_review_status: string
  script2_review_status: string
  script3_review_status: string
  script4_review_status: string
  script5_review_status: string
  script6_review_status: string
  script7_review_status: string
  // Meta
  notes?: string
  batch_id?: string
  stage_name?: string
  regulation_name?: string
  created_at: string
  updated_at: string
}

export interface HazardIdentificationFormData {
  hazard_id_no?: string  // 留空时后端自动生成 HI-YYYYMMDD-NNN
  department: string
  position: string
  production_step?: string  // 已取消输入
  regulation_id?: string  // 引用的安全操作规程 ID
  notes?: string
}

// ── 批量辨识 ──

export interface RegulationStageInfo {
  stage_name: string
  safety_count: number
  operation_count: number
}

export interface RegulationStagesResponse {
  regulation_id: string
  regulation_name?: string
  stages: RegulationStageInfo[]
}

export interface HazardIdentificationBatchCreateInput {
  regulation_id: string
  department: string
  position: string
  stage_names: string[]
  notes?: string
  auto_submit?: boolean
}

export interface HazardIdentificationBatchResponse {
  batch_id: string
  regulation_id: string
  regulation_name?: string
  records: HazardIdentification[]
  total_stages: number
  created_count: number
}

export interface HazardIdentificationQueryParams {
  page?: number
  page_size?: number
  department?: string
  overall_status?: string
  ai_node_progress?: string
  keyword?: string
  position?: string
  risk_level?: string
  date_from?: string
  date_to?: string
  batch_id?: string
}

export interface HazardIdentificationStats {
  total_draft: number
  total_in_progress: number
  total_pending_review: number
  total_completed: number
}

export interface HazardLedgerStats {
  total: number
  level_1: number
  level_2: number
  level_3: number
  level_4: number
}

export const AI_NODE_PROGRESS_OPTIONS = [
  { value: 'pending_input', label: '待填写基础信息', color: 'default' },
  { value: 'pending_script1', label: '待解析附件', color: 'processing' },
  { value: 'pending_script2', label: '待危险源辨识', color: 'processing' },
  { value: 'pending_script3', label: '待固有风险评价', color: 'processing' },
  { value: 'pending_script4', label: '待控制措施', color: 'processing' },
  { value: 'pending_script5', label: '待残余风险评价', color: 'processing' },
  { value: 'pending_script6', label: '待建议措施', color: 'processing' },
  { value: 'pending_script7', label: '待措施后评价', color: 'processing' },
  { value: 'completed', label: '已完成', color: 'success' },
]

// ============ Hazard Identification Export Types ============

export interface HazardLedgerExportRequest {
  natural_query?: string
  department?: string
  position?: string
  risk_level?: string
  date_from?: string
  date_to?: string
  keyword?: string
}

export interface HazardLedgerExportParsedFilters {
  department?: string
  position?: string
  risk_level?: string
  date_from?: string
  date_to?: string
  keyword?: string
  explanation: string
}

export const OVERALL_STATUS_OPTIONS_HI = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'in_progress', label: '进行中', color: 'processing' },
  { value: 'completed', label: '已完成', color: 'success' },
  { value: 'cancelled', label: '已取消', color: 'error' },
]

export const REVIEW_STATUS_OPTIONS = [
  { value: 'pending', label: '待审核', color: 'default' },
  { value: 'approved', label: '已审核', color: 'success' },
  { value: 'rejected', label: '已驳回', color: 'error' },
]

export const RECOMMENDATION_PRIORITY_OPTIONS = [
  { value: '高', label: '高', color: 'red' },
  { value: '中', label: '中', color: 'orange' },
  { value: '低', label: '低', color: 'blue' },
]
