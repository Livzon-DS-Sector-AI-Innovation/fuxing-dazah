// ============ SpecialOperationPersonnel Types ============
import { SpecialOperationType, OperationLevel, PersonnelStatus, PermitStatus, CompletionMethod } from "./enums"

export interface SpecialOperationPersonnel {
  id: string
  personnel_no: string
  name: string
  department?: string | null
  certificate_type: string
  certificate_number?: string | null
  issuing_authority?: string | null
  issue_date?: string | null
  expiry_date?: string | null
  certificate_file_path?: string | null
  qualification_scope?: string | null
  status: string
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface SpecialOperationPersonnelFormData {
  personnel_no: string
  name: string
  department?: string
  certificate_type: SpecialOperationType
  certificate_number?: string
  issuing_authority?: string
  issue_date?: string
  expiry_date?: string
  certificate_file_path?: string
  qualification_scope?: string
  notes?: string
}

export interface SpecialOperationPersonnelQueryParams {
  page?: number
  page_size?: number
  status?: string
  certificate_type?: string
  department?: string
  keyword?: string
}

// ============ SpecialOperationPermit Types ============

export interface SpecialOperationPermit {
  id: string
  permit_no: string
  operation_type: string
  operation_level: string
  location?: string | null
  equipment_tag?: string | null
  work_description?: string | null
  planned_start_time?: string | null
  planned_end_time?: string | null
  actual_start_time?: string | null
  actual_end_time?: string | null
  applicant_name?: string | null
  work_leader_name?: string | null
  operator_names?: string | null
  guardian_name?: string | null
  approver_name?: string | null
  safety_measures?: string | null
  emergency_equipment?: string | null
  gas_analysis?: string | null
  risk_assessment?: string | null
  safety_briefing_confirmed: boolean
  safety_briefing_time?: string | null
  rejection_reason?: string | null
  completion_method?: string | null
  status: string
  check_id?: string | null
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface SpecialOperationPermitFormData {
  permit_no: string
  operation_type: SpecialOperationType
  operation_level?: OperationLevel
  location?: string
  equipment_tag?: string
  work_description?: string
  planned_start_time?: string
  planned_end_time?: string
  applicant_name?: string
  work_leader_name?: string
  operator_names?: string
  guardian_name?: string
  approver_name?: string
  safety_measures?: string
  emergency_equipment?: string
  gas_analysis?: string
  risk_assessment?: string
  check_id?: string
  notes?: string
}

export interface SpecialOperationPermitQueryParams {
  page?: number
  page_size?: number
  status?: string
  operation_type?: string
  operation_level?: string
  keyword?: string
}

