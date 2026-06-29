// ==================== 职业危害因素监测 ====================


export enum DetectionType {
  REGULAR = 'regular',
  COMMISSIONED = 'commissioned',
  EVALUATION = 'evaluation',
  ACCIDENT = 'accident',
}

export const DETECTION_TYPE_OPTIONS = [
  { value: DetectionType.REGULAR, label: '定期检测' },
  { value: DetectionType.COMMISSIONED, label: '委托检测' },
  { value: DetectionType.EVALUATION, label: '评价检测' },
  { value: DetectionType.ACCIDENT, label: '事故调查检测' },
]

export enum HazardFactorCategory {
  DUST = 'dust',
  CHEMICAL = 'chemical',
  PHYSICAL = 'physical',
}

export const HAZARD_FACTOR_CATEGORY_OPTIONS = [
  { value: HazardFactorCategory.DUST, label: '粉尘（总尘/呼尘）' },
  { value: HazardFactorCategory.CHEMICAL, label: '化学物质' },
  { value: HazardFactorCategory.PHYSICAL, label: '物理因素' },
]

export enum OELComplianceStatus {
  COMPLIANT = 'compliant',
  EXCEEDING = 'exceeding',
  MARGINAL = 'marginal',
}

export const OEL_COMPLIANCE_STATUS_OPTIONS = [
  { value: OELComplianceStatus.COMPLIANT, label: '符合', color: 'green' },
  { value: OELComplianceStatus.EXCEEDING, label: '超标', color: 'red' },
  { value: OELComplianceStatus.MARGINAL, label: '临界', color: 'orange' },
]

export enum MonitorStatus {
  DRAFT = 'draft',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  VERIFIED = 'verified',
}

export const MONITOR_STATUS_OPTIONS = [
  { value: MonitorStatus.DRAFT, label: '草稿', color: 'default' },
  { value: MonitorStatus.IN_PROGRESS, label: '检测中', color: 'processing' },
  { value: MonitorStatus.COMPLETED, label: '已完成', color: 'green' },
  { value: MonitorStatus.VERIFIED, label: '已验证', color: 'cyan' },
]

export enum ExamType {
  PRE_EMPLOYMENT = 'pre_employment',
  PERIODIC = 'periodic',
  POST_EMPLOYMENT = 'post_employment',
  EMERGENCY = 'emergency',
}

export const EXAM_TYPE_OPTIONS = [
  { value: ExamType.PRE_EMPLOYMENT, label: '上岗前' },
  { value: ExamType.PERIODIC, label: '在岗期间' },
  { value: ExamType.POST_EMPLOYMENT, label: '离岗时' },
  { value: ExamType.EMERGENCY, label: '应急/事故后' },
]

export enum ExamConclusion {
  NORMAL = 'normal',
  ABNORMAL_OTHER = 'abnormal_other',
  SUSPECTED_OD = 'suspected_od',
  OD_DIAGNOSED = 'od_diagnosed',
  CONTRAINDICATED = 'contraindicated',
  RE_EXAMINATION = 're_examination',
}

export const EXAM_CONCLUSION_OPTIONS = [
  { value: ExamConclusion.NORMAL, label: '未见异常', color: 'green' },
  { value: ExamConclusion.ABNORMAL_OTHER, label: '其他异常', color: 'orange' },
  { value: ExamConclusion.SUSPECTED_OD, label: '疑似职业病', color: 'red' },
  { value: ExamConclusion.OD_DIAGNOSED, label: '职业病确诊', color: 'red' },
  { value: ExamConclusion.CONTRAINDICATED, label: '职业禁忌证', color: 'red' },
  { value: ExamConclusion.RE_EXAMINATION, label: '复查', color: 'blue' },
]

export enum ExamStatus {
  SCHEDULED = 'scheduled',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  ARCHIVED = 'archived',
}

export const EXAM_STATUS_OPTIONS = [
  { value: ExamStatus.SCHEDULED, label: '已安排', color: 'default' },
  { value: ExamStatus.IN_PROGRESS, label: '体检中', color: 'processing' },
  { value: ExamStatus.COMPLETED, label: '已完成', color: 'green' },
  { value: ExamStatus.ARCHIVED, label: '已归档', color: 'default' },
]

export enum AbnormalityStatus {
  OPEN = 'open',
  INVESTIGATING = 'investigating',
  CORRECTED = 'corrected',
  CLOSED = 'closed',
}

export const ABNORMALITY_STATUS_OPTIONS = [
  { value: AbnormalityStatus.OPEN, label: '待处理', color: 'red' },
  { value: AbnormalityStatus.INVESTIGATING, label: '调查中', color: 'orange' },
  { value: AbnormalityStatus.CORRECTED, label: '已纠正', color: 'green' },
  { value: AbnormalityStatus.CLOSED, label: '已关闭', color: 'default' },
]

// JSON 子记录接口
export interface DetectionResultItem {
  factor_name: string
  factor_category: string
  detection_value: number
  unit?: string
  oel_limit?: number
  compliance_status?: string
  sampling_method?: string
  standard_ref?: string
}

export interface ExamResultItem {
  item_name: string
  category?: string
  result?: string
  reference_range?: string
  is_abnormal?: boolean
  remarks?: string
}

export interface AbnormalityRecord {
  abnormality_desc: string
  corrective_action?: string
  responsible_person?: string
  deadline?: string
  status?: string
  completed_at?: string
  remarks?: string
}

// 主实体接口
export interface OhHazardMonitor {
  id: string
  monitor_no: string
  workplace: string
  location?: string
  equipment_info?: string
  detection_type: string
  detection_date?: string
  detection_agency?: string
  status: string
  inspector_name?: string
  verifier_name?: string
  detection_results?: DetectionResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
  created_at: string
  updated_at: string
}

export interface OhHealthExam {
  id: string
  exam_no: string
  employee_name: string
  employee_id?: string
  department?: string
  job_position?: string
  exam_type: string
  status: string
  exam_agency?: string
  scheduled_date?: string
  exam_date?: string
  report_date?: string
  hazard_factors?: string[]
  overall_conclusion?: string
  exam_items?: ExamResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
  created_at: string
  updated_at: string
}

// FormData 接口
export interface OhHazardMonitorFormData {
  monitor_no: string
  workplace: string
  location?: string
  equipment_info?: string
  detection_type: string
  detection_date?: string
  detection_agency?: string
  inspector_name?: string
  detection_results?: DetectionResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
}

export interface OhHealthExamFormData {
  exam_no: string
  employee_name: string
  employee_id?: string
  department?: string
  job_position?: string
  exam_type: string
  exam_agency?: string
  scheduled_date?: string
  exam_date?: string
  report_date?: string
  hazard_factors?: string[]
  overall_conclusion?: string
  exam_items?: ExamResultItem[]
  abnormality_records?: AbnormalityRecord[]
  attachments?: { name: string; path: string }[]
  notes?: string
}

// QueryParams 接口
export interface OhHazardMonitorQueryParams {
  page?: number
  page_size?: number
  status?: string
  detection_type?: string
  workplace?: string
  keyword?: string
}

export interface OhHealthExamQueryParams {
  page?: number
  page_size?: number
  status?: string
  exam_type?: string
  department?: string
  keyword?: string
}

