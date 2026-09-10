
// ============ EHS变更管理 (MOC) ============

// Enums
export enum ChangeType {
  PROCESS_TECH = 'process_tech',
  EQUIPMENT_FACILITY = 'equipment_facility',
  MANAGEMENT = 'management',
}

export const CHANGE_TYPE_OPTIONS = [
  { value: ChangeType.PROCESS_TECH, label: '工艺技术变更' },
  { value: ChangeType.EQUIPMENT_FACILITY, label: '设备设施变更' },
  { value: ChangeType.MANAGEMENT, label: '管理变更' },
]

export enum ChangeGrade {
  MAJOR = 'major',
  GENERAL = 'general',
}

export const CHANGE_GRADE_OPTIONS = [
  { value: ChangeGrade.MAJOR, label: '重大变更', color: 'red' },
  { value: ChangeGrade.GENERAL, label: '一般变更', color: 'blue' },
]

export enum ChangeDuration {
  PERMANENT = 'permanent',
  TEMPORARY = 'temporary',
  EMERGENCY = 'emergency',
}

export const CHANGE_DURATION_OPTIONS = [
  { value: ChangeDuration.PERMANENT, label: '永久性' },
  { value: ChangeDuration.TEMPORARY, label: '临时性' },
  { value: ChangeDuration.EMERGENCY, label: '紧急', color: 'red' },
]

export enum EhsChangeStatus {
  DRAFT = 'draft',
  UNDER_REVIEW = 'under_review',
  APPROVED = 'approved',
  REJECTED = 'rejected',
  IN_PROGRESS = 'in_progress',
  COMMISSIONED = 'commissioned',
  CLOSED = 'closed',
}

export const EHS_CHANGE_STATUS_OPTIONS = [
  { value: EhsChangeStatus.DRAFT, label: '草稿', color: 'default' },
  { value: EhsChangeStatus.UNDER_REVIEW, label: '审核中', color: 'processing' },
  { value: EhsChangeStatus.APPROVED, label: '已批准', color: 'green' },
  { value: EhsChangeStatus.REJECTED, label: '已驳回', color: 'red' },
  { value: EhsChangeStatus.IN_PROGRESS, label: '实施中', color: 'orange' },
  { value: EhsChangeStatus.COMMISSIONED, label: '已投用', color: 'cyan' },
  { value: EhsChangeStatus.CLOSED, label: '已关闭', color: 'default' },
]

export enum RiskLevel {
  LEVEL_1 = 'level_1',
  LEVEL_2 = 'level_2',
  LEVEL_3 = 'level_3',
  LEVEL_4 = 'level_4',
}

export const RISK_LEVEL_OPTIONS = [
  { value: RiskLevel.LEVEL_1, label: '一级/重大风险', color: 'red' },
  { value: RiskLevel.LEVEL_2, label: '二级/较大风险', color: 'orange' },
  { value: RiskLevel.LEVEL_3, label: '三级/一般风险', color: 'yellow' },
  { value: RiskLevel.LEVEL_4, label: '四级/低风险', color: 'blue' },
]

export enum RiskAssessmentMethod {
  LEC = 'LEC',
  LS = 'LS',
  JHA = 'JHA',
  HAZOP = 'HAZOP',
  FMEA = 'FMEA',
  SCL = 'SCL',
  PHA = 'PHA',
  LOPA = 'LOPA',
  OTHER = 'other',
}

export const RISK_ASSESSMENT_METHOD_OPTIONS = [
  { value: RiskAssessmentMethod.LEC, label: 'LEC评价法' },
  { value: RiskAssessmentMethod.LS, label: 'LS风险矩阵' },
  { value: RiskAssessmentMethod.JHA, label: 'JHA工作危害分析' },
  { value: RiskAssessmentMethod.HAZOP, label: 'HAZOP分析' },
  { value: RiskAssessmentMethod.FMEA, label: 'FMEA失效模式分析' },
  { value: RiskAssessmentMethod.SCL, label: 'SCL安全检查表' },
  { value: RiskAssessmentMethod.PHA, label: 'PHA预先危险性分析' },
  { value: RiskAssessmentMethod.LOPA, label: 'LOPA保护层分析' },
  { value: RiskAssessmentMethod.OTHER, label: '其他' },
]

export enum ApprovalDecision {
  PENDING = 'pending',
  APPROVED = 'approved',
  REJECTED = 'rejected',
}

export const APPROVAL_DECISION_OPTIONS = [
  { value: ApprovalDecision.PENDING, label: '待审批', color: 'default' },
  { value: ApprovalDecision.APPROVED, label: '同意', color: 'green' },
  { value: ApprovalDecision.REJECTED, label: '驳回', color: 'red' },
]

export enum ActionItemStatus {
  PENDING = 'pending',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
}

export const ACTION_ITEM_STATUS_OPTIONS = [
  { value: ActionItemStatus.PENDING, label: '待完成' },
  { value: ActionItemStatus.IN_PROGRESS, label: '进行中' },
  { value: ActionItemStatus.COMPLETED, label: '已完成' },
]

export enum PSSRResult {
  PASS = 'pass',
  FAIL = 'fail',
  NA = 'na',
}

export const PSSR_RESULT_OPTIONS = [
  { value: PSSRResult.PASS, label: '通过', color: 'green' },
  { value: PSSRResult.FAIL, label: '不通过', color: 'red' },
  { value: PSSRResult.NA, label: '不适用', color: 'default' },
]

// JSON sub-record interfaces
export interface RiskAssessmentItem {
  method?: string
  severity?: string
  likelihood?: string
  risk_level?: string
  description?: string
  control_measures?: string
  assessed_by?: string
  assessed_date?: string
  participants?: string
}

export interface ApprovalChainItem {
  level: number
  approver_role: string
  approver?: string
  decision?: string
  comments?: string
  decided_at?: string
}

export interface ActionItem {
  task: string
  owner?: string
  due_date?: string
  status?: string
  completed_at?: string
}

export interface PSSRChecklistItem {
  item: string
  result?: string
  checked_by?: string
  checked_at?: string
  remarks?: string
}

export interface VerificationData {
  expected_effect_achieved?: boolean
  comments?: string
  psi_updated?: boolean
  documents_updated?: boolean
  accepted_by?: string
  accepted_date?: string
}

export interface ClosureData {
  closed_by?: string
  closed_date?: string
  temp_expiry_date?: string
  restored_date?: string
}

// AI 审核维度（Bitable 审批表四维度）
export interface EhsAiReviewDimension {
  conclusion?: string | null
  report?: string | null
}

export interface EhsAiReviewResult {
  reason?: EhsAiReviewDimension
  plan?: EhsAiReviewDimension
  effect?: EhsAiReviewDimension
  risk?: EhsAiReviewDimension
  pre_review?: string
  /** AI 审核依据的法规来源（RAG 检索） */
  regulations?: { doc_title?: string; article_ref?: string }[]
}

export type EhsChangeSource = 'manual' | 'bitable'
export type EhsChangeTableId = 'approval' | 'acceptance'

// Main interfaces
export interface EhsChange {
  id: string
  change_no: string
  title: string
  change_type?: string | null
  change_grade: string
  change_duration?: string | null
  department?: string
  location_unit?: string
  description?: string
  technical_basis?: string
  expected_start?: string
  expected_completion?: string
  actual_start?: string
  actual_completion?: string
  expected_effect?: string
  applicant_id?: string
  applicant_name?: string
  status: string
  equipment_tags?: string[]
  documents_to_update?: { name: string; number?: string }[]
  attachments?: { name: string; path: string }[]
  risk_assessments?: RiskAssessmentItem[]
  approval_chain?: ApprovalChainItem[]
  action_items?: ActionItem[]
  pssr_checklist?: PSSRChecklistItem[]
  verification?: VerificationData
  closure?: ClosureData
  linked_safety_check_id?: string
  notes?: string
  // Bitable 同步字段
  source?: EhsChangeSource
  feishu_record_id?: string
  feishu_table_id?: EhsChangeTableId
  bt_change_no?: string
  bt_change_status?: string
  bt_plan_content?: string
  bt_risk_measures?: string
  bt_acceptance_comment?: string
  bt_extra?: {
    can_reflect?: string
    gmp_change_no?: string
    current_handler?: string
    approval_node?: string
    source_id?: string
    approval_flow?: string
    related_approval?: string
    acceptance_date?: string
    feishu_url?: string
  }
  ai_review_status?: string
  ai_review_result?: EhsAiReviewResult
  ai_error_message?: string
  created_at: string
  updated_at: string
}

export interface EhsChangeFormData {
  change_no: string
  title: string
  change_type: string
  change_grade?: string
  change_duration?: string
  department?: string
  applicant_name?: string
  description?: string
  expected_effect?: string
  expected_start?: string
  documents_to_update?: { name: string; number?: string }[]
  // 清单字段（变更内容）
  bt_plan_content?: string
  bt_risk_measures?: string
}

export interface EhsChangeQueryParams {
  page?: number
  page_size?: number
  status?: string
  change_type?: string
  change_grade?: string
  change_duration?: string
  department?: string
  keyword?: string
  source?: string
  feishu_table_id?: string
  sort_by?: string
  sort_order?: string
}

export interface EhsChangeStats {
  total: number
  status: Record<string, number>
  ai: Record<string, number>
}


