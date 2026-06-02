// safety module TypeScript types

export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
  meta?: {
    page?: number
    page_size?: number
    total?: number
  }
}

// ============ Enums ============

export enum CheckType {
  DAILY = 'daily',
  SPECIAL = 'special',
  COMPREHENSIVE = 'comprehensive',
  HOLIDAY = 'holiday',
}

export const CHECK_TYPE_OPTIONS = [
  { value: CheckType.DAILY, label: '日常检查' },
  { value: CheckType.SPECIAL, label: '专项检查' },
  { value: CheckType.COMPREHENSIVE, label: '综合检查' },
  { value: CheckType.HOLIDAY, label: '节假日检查' },
]

export enum HazardType {
  UNSAFE_CONDITION = 'unsafe_condition',
  UNSAFE_ACTION = 'unsafe_action',
  MANAGEMENT_DEFECT = 'management_defect',
  ENVIRONMENTAL = 'environmental',
}

export const HAZARD_TYPE_OPTIONS = [
  { value: HazardType.UNSAFE_CONDITION, label: '物的不安全状态' },
  { value: HazardType.UNSAFE_ACTION, label: '人的不安全行为' },
  { value: HazardType.MANAGEMENT_DEFECT, label: '管理缺陷' },
  { value: HazardType.ENVIRONMENTAL, label: '环境因素' },
]

export enum HazardLevel {
  GENERAL = 'general',
  MAJOR = 'major',
}

export const HAZARD_LEVEL_OPTIONS = [
  { value: HazardLevel.GENERAL, label: '一般隐患', color: 'blue' },
  { value: HazardLevel.MAJOR, label: '重大隐患', color: 'red' },
]

export enum AccidentType {
  INJURY = 'injury',
  FIRE = 'fire',
  EXPLOSION = 'explosion',
  LEAKAGE = 'leakage',
  EQUIPMENT = 'equipment',
  OTHER = 'other',
}

export const ACCIDENT_TYPE_OPTIONS = [
  { value: AccidentType.INJURY, label: '工伤事故' },
  { value: AccidentType.FIRE, label: '火灾' },
  { value: AccidentType.EXPLOSION, label: '爆炸' },
  { value: AccidentType.LEAKAGE, label: '泄漏' },
  { value: AccidentType.EQUIPMENT, label: '设备事故' },
  { value: AccidentType.OTHER, label: '其他' },
]

export enum AccidentLevel {
  GENERAL = 'general',
  SERIOUS = 'serious',
  MAJOR = 'major',
  CATASTROPHIC = 'catastrophic',
}

export const ACCIDENT_LEVEL_OPTIONS = [
  { value: AccidentLevel.GENERAL, label: '一般事故', color: 'blue' },
  { value: AccidentLevel.SERIOUS, label: '较大事故', color: 'orange' },
  { value: AccidentLevel.MAJOR, label: '重大事故', color: 'red' },
  { value: AccidentLevel.CATASTROPHIC, label: '特别重大事故', color: 'magenta' },
]

export enum TrainingType {
  INDUCTION = 'induction',
  ANNUAL = 'annual',
  SPECIAL = 'special',
  EMERGENCY = 'emergency',
}

export const TRAINING_TYPE_OPTIONS = [
  { value: TrainingType.INDUCTION, label: '入职培训' },
  { value: TrainingType.ANNUAL, label: '年度培训' },
  { value: TrainingType.SPECIAL, label: '专项培训' },
  { value: TrainingType.EMERGENCY, label: '应急培训' },
]

export enum TrainingMode {
  ONLINE = 'online',
  OFFLINE = 'offline',
  BLENDED = 'blended',
}

export const TRAINING_MODE_OPTIONS = [
  { value: TrainingMode.ONLINE, label: '线上' },
  { value: TrainingMode.OFFLINE, label: '线下' },
  { value: TrainingMode.BLENDED, label: '混合' },
]

export const CHECK_RESULT_OPTIONS = [
  { value: 'qualified', label: '合格', color: 'success' },
  { value: 'unqualified', label: '不合格', color: 'error' },
  { value: 'need_rectification', label: '需整改', color: 'warning' },
]

export const RECTIFICATION_STATUS_OPTIONS = [
  { value: 'pending', label: '待整改', color: 'default' },
  { value: 'in_progress', label: '整改中', color: 'processing' },
  { value: 'completed', label: '已完成', color: 'success' },
  { value: 'verified', label: '已验证', color: 'blue' },
]

export const HAZARD_STATUS_OPTIONS = [
  { value: 'open', label: '待处理', color: 'default' },
  { value: 'closed', label: '已关闭', color: 'success' },
]

export const ACCIDENT_STATUS_OPTIONS = [
  { value: 'reported', label: '已报告', color: 'default' },
  { value: 'investigating', label: '调查中', color: 'processing' },
  { value: 'resolved', label: '已处理', color: 'success' },
  { value: 'closed', label: '已关闭', color: 'blue' },
]

export const CHECK_STATUS_OPTIONS = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'submitted', label: '已提交', color: 'blue' },
  { value: 'reviewed', label: '已审核', color: 'success' },
  { value: 'closed', label: '已关闭', color: 'default' },
]

export const TRAINING_STATUS_OPTIONS = [
  { value: 'draft', label: '草稿', color: 'default' },
  { value: 'in_progress', label: '进行中', color: 'processing' },
  { value: 'completed', label: '已完成', color: 'success' },
  { value: 'archived', label: '已归档', color: 'default' },
]

// ============ SafetyCheck Types ============

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

// ============ HazardReport Types ============

export interface HazardReport {
  id: string
  hazard_no: string
  hazard_type: HazardType
  hazard_level: HazardLevel
  description: string
  location?: string
  discovered_by?: string
  discovered_by_name?: string
  discovered_at: string
  department?: string
  control_measures?: string
  deadline?: string
  rectification_status: string
  verified_by?: string
  verified_by_name?: string
  verified_at?: string
  status: string
  check_id?: string
  notes?: string
  created_at: string
  updated_at: string
}

export interface HazardReportFormData {
  hazard_no: string
  hazard_type: HazardType
  hazard_level: HazardLevel
  description: string
  location?: string
  discovered_by?: string
  discovered_by_name?: string
  discovered_at: string
  department?: string
  control_measures?: string
  deadline?: string
  check_id?: string
  notes?: string
}

export interface HazardReportQueryParams {
  page?: number
  page_size?: number
  status?: string
  hazard_type?: string
  hazard_level?: string
  department?: string
}

// ============ Accident Types ============

export interface Accident {
  id: string
  accident_no: string
  accident_type: AccidentType
  accident_level: AccidentLevel
  happened_at: string
  location?: string
  description: string
  casualties?: string
  property_damage?: number
  direct_cause?: string
  root_cause?: string
  handling_measures?: string
  corrective_actions?: string
  status: string
  reported_by?: string
  reported_by_name?: string
  reported_at: string
  investigator?: string
  investigator_name?: string
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
  description: string
  casualties?: string
  property_damage?: number
  direct_cause?: string
  root_cause?: string
  handling_measures?: string
  corrective_actions?: string
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
}

// ============ SafetyTraining Types ============

export interface SafetyTraining {
  id: string
  training_no: string
  training_name: string
  training_type: TrainingType
  training_mode: TrainingMode
  trainer?: string
  trainer_name?: string
  training_date: string
  duration_hours?: number
  location?: string
  content?: string
  department?: string
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
  trainer?: string
  trainer_name?: string
  training_date: string
  duration_hours?: number
  location?: string
  content?: string
  department?: string
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
  attendance: boolean
  score?: number
  passed?: boolean
  notes?: string
  created_at: string
  updated_at: string
}

export interface TrainingRecordFormData {
  employee_id?: string
  employee_name?: string
  department?: string
  attendance?: boolean
  score?: number
  passed?: boolean
  notes?: string
}

// ============ Dashboard/Stats Types ============

export interface SafetyDashboardStats {
  total_checks: number
  pending_checks: number
  open_hazards: number
  overdue_hazards: number
  recent_accidents: number
  upcoming_trainings: number
}
