// ============ Accident Types ============

import { AccidentType, AccidentLevel, AccidentStatus, InjurySeverity, CheckType } from "./enums"
export interface Accident {
  id: string
  accident_no: string
  accident_type: AccidentType
  accident_level: AccidentLevel
  happened_at: string
  location?: string
  department?: string
  description: string
  casualties?: string
  property_damage?: number
  loss_work_days?: number
  injury_details?: { name: string; position: string; injury_part: string; severity: string; hospital?: string }[]
  investigation_team?: { name: string; role: string }[]
  investigation_method?: string
  investigation_findings?: string
  investigation_report_path?: string
  direct_cause?: string
  root_cause?: string
  handling_measures?: string
  corrective_actions?: string
  corrective_action_deadline?: string
  corrective_action_responsible?: string
  corrective_action_status?: string
  status: string
  reported_by?: string
  reported_by_name?: string
  reported_at: string
  investigator?: string
  investigator_name?: string
  verified_by?: string
  verified_by_name?: string
  verified_at?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface AccidentFormData {
  accident_no: string
  accident_type: AccidentType
  accident_level: AccidentLevel
  happened_at: string
  location?: string
  department?: string
  description: string
  casualties?: string
  property_damage?: number
  loss_work_days?: number
  injury_details?: { name: string; position: string; injury_part: string; severity: string; hospital?: string }[]
  investigation_team?: { name: string; role: string }[]
  investigation_method?: string
  investigation_findings?: string
  investigation_report_path?: string
  direct_cause?: string
  root_cause?: string
  handling_measures?: string
  corrective_actions?: string
  corrective_action_deadline?: string
  corrective_action_responsible?: string
  corrective_action_status?: string
  reported_by?: string
  reported_by_name?: string
  reported_at: string
  notes?: string
}

export interface AccidentQueryParams {
  page?: number
  page_size?: number
  status?: string
  accident_type?: string
  accident_level?: string
  department?: string
  date_from?: string
  date_to?: string
  keyword?: string
}

