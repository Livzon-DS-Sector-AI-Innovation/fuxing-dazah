// ============ SafetyCheck Types ============

import { CheckType } from "./enums"
export interface SafetyCheck {
  id: string
  check_no: string
  check_type: CheckType
  check_date: string
  department?: string
  inspector?: string
  inspector_name?: string
  location?: string
  findings?: string
  result?: string
  rectification_required: boolean
  rectification_deadline?: string
  rectification_status?: string
  inspector_confirmed: boolean
  safety_officer_confirmed: boolean
  status: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface SafetyCheckFormData {
  check_no: string
  check_type: CheckType
  check_date: string
  department?: string
  inspector?: string
  inspector_name?: string
  location?: string
  findings?: string
  result?: string
  rectification_required?: boolean
  rectification_deadline?: string
  notes?: string
}

export interface SafetyCheckQueryParams {
  page?: number
  page_size?: number
  status?: string
  check_type?: string
  department?: string
}

