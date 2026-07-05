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
