// ============ HazardReport Types ============

import { HazardType, HazardLevel, HazardCategory } from "./enums"
export interface HazardReport {
  id: string
  hazard_no: string
  inspection_category?: string
  hazard_type: HazardType
  hazard_level: HazardLevel
  hazard_category?: HazardCategory
  description: string
  discovered_by?: string
  discovered_by_name?: string
  inspector_department?: string
  discovered_at: string
  department?: string
  major_hazard_basis?: string
  key_defect?: string
  defect_photos?: string
  rectification_responsible_person?: string
  rectification_responsible_person_name?: string
  corrective_preventive_measures?: string
  rectification_reply?: string
  deadline?: string
  actual_completion_date?: string
  rectification_photos?: string
  rectification_status: string
  // 三级复核（仅状态，审核人/时间由系统自动记录）
  verify_level_1_status: string
  verify_level_2_status: string
  verify_level_3_status: string
  status: string
  check_id?: string
  notes?: string
  // ── AI 流程字段 ──
  ai_node_progress: string
  overall_status: string
  ai_error_message?: string
  ai_generated: boolean
  script1_review_status: string
  script2_review_status: string
  // ── AI 整改初审 ──
  ai_review_result?: Record<string, any> | null
  ai_review_status: string
  ai_review_completed_at?: string | null
  created_at: string
  updated_at: string
  // ── 飞书通知追踪 ──
  rectification_notified_at?: string | null
  rectification_notify_status?: string | null
  rectification_notify_error?: string | null
  review_notified_at?: string | null
  review_notified_level?: number | null
  review_notify_status?: string | null
  review_notify_error?: string | null
}

export interface HazardReportFormData {
  hazard_no: string
  inspection_category?: string
  inspector_department?: string
  hazard_type?: HazardType
  hazard_level?: HazardLevel
  hazard_category?: HazardCategory
  description?: string
  discovered_by?: string
  discovered_by_name?: string
  discovered_at?: string
  department?: string
  major_hazard_basis?: string
  key_defect?: string
  defect_photos?: string
  rectification_responsible_person?: string
  rectification_responsible_person_name?: string
  corrective_preventive_measures?: string
  rectification_reply?: string
  deadline?: string
  actual_completion_date?: string
  rectification_photos?: string
  check_id?: string
  notes?: string
  overall_status?: string
}

export interface HazardReportQueryParams {
  page?: number
  page_size?: number
  status?: string
  rectification_status?: string
  overall_status?: string
  hazard_type?: string
  hazard_level?: string
  hazard_category?: string
  inspection_category?: string
  department?: string
  keyword?: string
}

export interface HazardStats {
  total: number
  pending_review: number
  pending: number
  in_progress: number
  replied: number
  verifying: number
  rejected: number
  closed: number
  overdue: number
}

export interface RectificationReplyRequest {
  reply_content: string
  rectification_photos?: string
  corrective_preventive_measures?: string
  rectification_reply?: string
  actual_completion_date?: string
}

export interface VerifyLevelRequest {
  level: number
  action: 'approved' | 'rejected'
  opinion?: string
}

export interface ConfirmCheckRequest {
  role: 'inspector' | 'safety_officer'
}

