// ==================== 风险作业报备 ====================

import { SpecialOperationType } from './enums'
export enum ReportStatus {
  DRAFT = 'draft',
  SUBMITTED = 'submitted',
  APPROVED = 'approved',
  REJECTED = 'rejected',
}

export const REPORT_STATUS_OPTIONS = [
  { value: ReportStatus.DRAFT, label: '草稿', color: 'default' },
  { value: ReportStatus.SUBMITTED, label: '已提交', color: 'blue' },
  { value: ReportStatus.APPROVED, label: '已审批', color: 'green' },
  { value: ReportStatus.REJECTED, label: '已驳回', color: 'red' },
]

export const REPORT_TYPE_OPTIONS = [
  { value: 'regular', label: '常规作业', color: 'blue' },
  { value: 'non_regular', label: '非常规作业', color: 'orange' },
]

// ── 八大特殊作业报备 ──

export interface SpecialOperationReport {
  id: string
  report_no: string
  permit_id?: string
  operation_type: string
  operation_level: string
  department?: string
  location?: string
  equipment_tag?: string
  work_description?: string
  planned_start_time?: string
  planned_end_time?: string
  work_leader_name?: string
  operator_names?: string
  guardian_name?: string
  risk_level?: string
  safety_measures?: string
  emergency_equipment?: string
  gas_analysis?: string
  risk_assessment?: string
  applicant_name?: string
  approver_name?: string
  approved_at?: string
  rejection_reason?: string
  status: string
  notes?: string
  is_critical: boolean
  is_critical_reason?: string
  is_critical_updated_by?: string
  // Bitable sync fields
  source?: string
  feishu_record_id?: string
  personnel_type?: string
  work_duration_hours?: number
  has_other_operations?: string
  other_operation_types?: string[]
  is_weekend_holiday?: string
  is_national_holiday?: string
  holiday_period?: string
  report_type?: string
  initiator_department?: string
  initiator_name?: string
  approver_type?: string
  safety_approver_name?: string
  approval_no?: string
  work_plan_url?: string
  work_scheme_url?: string
  approved_permit_url?: string
  submitted_at?: string
  completed_at?: string
  approval_node?: string
  // Daily report analysis
  daily_risk_level?: string
  daily_risk_reason?: string
  inferred_operation_types?: string[]
  inferred_operation_detail?: string
  is_excluded?: boolean
  exclusion_reason?: string
  daily_report_date?: string
  // V3.5 风险判定字段
  fire_work_method?: string | null
  height_work_method?: string | null
  work_height?: number | null
  lifting_weight?: number | null
  contractor_name?: string | null
  created_at: string
  updated_at: string
}

export interface SpecialOperationReportFormData {
  report_no: string
  permit_id?: string
  operation_type: string
  operation_level: string
  department?: string
  location?: string
  equipment_tag?: string
  work_description?: string
  planned_start_time?: string
  planned_end_time?: string
  work_leader_name?: string
  operator_names?: string
  guardian_name?: string
  risk_level?: string
  safety_measures?: string
  emergency_equipment?: string
  gas_analysis?: string
  risk_assessment?: string
  applicant_name?: string
  approver_name?: string
  notes?: string
}

export interface SpecialOperationReportQueryParams {
  page?: number
  page_size?: number
  status?: string
  operation_type?: string
  operation_level?: string
  risk_level?: string
  department?: string
  date_from?: string
  date_to?: string
  keyword?: string
  is_critical?: boolean
}

/** V3.5 风险判定字段（平台直输/同步，PUT 更新用） */
export interface SpecialOperationReportV35Fields {
  fire_work_method?: string | null
  height_work_method?: string | null
  work_height?: number | null
  lifting_weight?: number | null
  contractor_name?: string | null
}

// ── 特殊作业台账 ──

export interface SpecialOperationLedgerQueryParams {
  page?: number
  page_size?: number
  operation_type?: string
  operation_level?: string
  risk_level?: string
  department?: string
  date_from?: string
  date_to?: string
  keyword?: string
  is_critical?: boolean
}

export interface SpecialOperationLedgerStats {
  operation_type: string
  count: number
  critical_count: number
}

// ── 关键风险作业报备（Bitable 只读）→ 见 ./key-risk-operation.ts ──

