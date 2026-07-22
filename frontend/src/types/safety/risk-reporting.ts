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

// ── 危险源选项（用于每日风险报备关联） ──

export interface HazardRiskOption {
  id: string
  hazard_id_no: string
  department: string
  position: string
  specific_activity: string
  inherent_risk_level: string
  inherent_risk_label: string
  existing_engineering_controls?: string
  existing_management_controls?: string
  existing_ppe?: string
  existing_emergency_measures?: string
}

// ── 每日风险作业报备 ──

export interface DailyRiskReport {
  id: string
  report_no: string
  report_date: string
  report_type?: string
  department?: string
  hazard_identification_id?: string
  operation_description: string
  operation_steps?: string
  hazard_factors?: string
  risk_level?: string
  control_measures?: string
  responsible_person?: string
  operator_count?: number
  location?: string
  planned_start_time?: string
  planned_end_time?: string
  applicant_name?: string
  approver_name?: string
  approved_at?: string
  rejection_reason?: string
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface DailyRiskReportFormData {
  report_no: string
  report_date: string
  report_type?: string
  department?: string
  hazard_identification_id?: string
  operation_description: string
  operation_steps?: string
  hazard_factors?: string
  risk_level?: string
  control_measures?: string
  responsible_person?: string
  operator_count?: number
  location?: string
  planned_start_time?: string
  planned_end_time?: string
  applicant_name?: string
  approver_name?: string
  notes?: string
}

export interface DailyRiskReportQueryParams {
  page?: number
  page_size?: number
  status?: string
  department?: string
  report_date?: string
  report_type?: string
  keyword?: string
}

