// ============ SafetyTraining Types ============

import { TrainingType, TrainingMode, TrainingLevel, CertificateStatus } from "./enums"
export interface SafetyTraining {
  id: string
  training_no: string
  training_name: string
  training_type: TrainingType
  training_mode: TrainingMode
  training_level?: string
  trainer?: string
  trainer_name?: string
  training_date: string
  duration_hours?: number
  location?: string
  content?: string
  department?: string
  exam_passing_score?: number
  course_material_path?: string
  status: string
  notes?: string
  created_at: string
  updated_at: string
  records?: TrainingRecord[]
}

export interface SafetyTrainingFormData {
  training_no: string
  training_name: string
  training_type: TrainingType
  training_mode: TrainingMode
  training_level?: string
  trainer?: string
  trainer_name?: string
  training_date: string
  duration_hours?: number
  location?: string
  content?: string
  department?: string
  exam_passing_score?: number
  course_material_path?: string
  notes?: string
}

export interface SafetyTrainingQueryParams {
  page?: number
  page_size?: number
  status?: string
  training_type?: string
  department?: string
}

// ============ TrainingRecord Types ============

export interface TrainingRecord {
  id: string
  training_id: string
  employee_id?: string
  employee_name?: string
  department?: string
  position?: string
  attendance: boolean
  score?: number
  passed?: boolean
  certificate_no?: string
  certificate_expiry?: string
  certificate_status?: string
  certificate_file_path?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface TrainingRecordFormData {
  employee_id?: string
  employee_name?: string
  department?: string
  position?: string
  attendance?: boolean
  score?: number
  passed?: boolean
  certificate_no?: string
  certificate_expiry?: string
  certificate_file_path?: string
  notes?: string
}

// ============ HazardIdentification Types ============
