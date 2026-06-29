// ============ Contractor Types ============

import { ContractorStatus, QualificationTypeEnum, QualificationLevelEnum, ContractorTrainingStatusEnum, WorkRecordStatusEnum } from "./enums"
export interface Contractor {
  id: string
  contractor_no: string
  company_name: string
  legal_representative?: string
  contact_person: string
  contact_phone?: string
  business_scope?: string
  qualification_type: QualificationTypeEnum
  qualification_level?: QualificationLevelEnum
  qualification_cert_no?: string
  qualification_expiry?: string
  safety_license_no?: string
  safety_license_expiry?: string
  insurance_info?: string
  insurance_expiry?: string
  safety_officer_name?: string
  safety_officer_phone?: string
  special_op_personnel?: { name: string; cert_type: string; cert_no: string; expiry?: string }[]
  training_status: string
  training_date?: string
  safety_performance_score?: number
  blacklisted: boolean
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface ContractorFormData {
  contractor_no: string
  company_name: string
  legal_representative?: string
  contact_person: string
  contact_phone?: string
  business_scope?: string
  qualification_type: QualificationTypeEnum
  qualification_level?: QualificationLevelEnum
  qualification_cert_no?: string
  qualification_expiry?: string
  safety_license_no?: string
  safety_license_expiry?: string
  insurance_info?: string
  insurance_expiry?: string
  safety_officer_name?: string
  safety_officer_phone?: string
  special_op_personnel?: { name: string; cert_type: string; cert_no: string; expiry?: string }[]
  notes?: string
}

export interface ContractorQueryParams {
  page?: number
  page_size?: number
  status?: string
  qualification_type?: string
  training_status?: string
  keyword?: string
}

export interface ContractorWorkRecord {
  id: string
  contractor_id: string
  work_content: string
  work_location?: string
  planned_start: string
  planned_end: string
  actual_start?: string
  actual_end?: string
  permit_id?: string
  leading_person?: string
  worker_count?: number
  safety_briefing_done: boolean
  violations?: { date: string; description: string; severity: string; handler?: string; result?: string }[]
  evaluation?: { score: number; comments?: string; evaluator?: string; date?: string }
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface ContractorWorkRecordFormData {
  work_content: string
  work_location?: string
  planned_start: string
  planned_end: string
  actual_start?: string
  actual_end?: string
  permit_id?: string
  leading_person?: string
  worker_count?: number
  safety_briefing_done: boolean
  violations?: { date: string; description: string; severity: string; handler?: string; result?: string }[]
  notes?: string
}

