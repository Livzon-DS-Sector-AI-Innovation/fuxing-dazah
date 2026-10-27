// QA 偏差管理（偏差调查 + CAPA）类型，对应后端 app/modules/qa/deviation_*。

export type DeviationStatus = 'draft' | 'investigating' | 'assessing' | 'closed'
export type DeviationClassification = 'minor' | 'moderate' | 'critical'
export type RootCauseCategory = 'personnel' | 'equipment' | 'material' | 'method' | 'environment' | 'other'
export type QualityImpact = 'affected' | 'not_affected'
export type DeviationItemCategory =
  | 'material'
  | 'intermediate'
  | 'finished'
  | 'in_process'
  | 'equipment'
  | 'document'
  | 'other'
export type DeviationTransitionAction = 'start_investigation' | 'submit_assessment' | 'close'

export interface WhyStep {
  question: string
  answer: string
}

export interface DeviationItem {
  id?: string
  category: DeviationItemCategory
  name: string
  batch_no?: string | null
  handling?: string | null
}

export interface DeviationHypothesisTest {
  id?: string
  sample?: string | null
  hypothesis: string
  protocol?: string | null
  expected?: string | null
  result?: string | null
  conclusion?: string | null
  tested_by?: string | null
  tested_at?: string | null
}

export interface StatusLog {
  id: string
  action: string
  from_status: string | null
  to_status: string | null
  operator_name: string | null
  comment: string | null
  created_at: string
}

export interface DeviationAttachment {
  id: string
  file_name: string
  mime_type: string
  file_size: number
  sha256: string
  uploaded_by_name: string | null
  created_at: string
}

export interface DeviationBrief {
  id: string
  deviation_no: string
  status: DeviationStatus
  discovery_date: string
  occurrence_date: string | null
  due_date: string
  /** 未关闭时为距关闭期限的天数（可为负），已关闭为 null。 */
  days_remaining: number | null
  is_overdue: boolean
  /** 登记日晚于发现日次日，即超过 SOP 的 24 小时书面报告时限。 */
  reported_late: boolean
  department_name: string | null
  group_name: string | null
  reporter_name: string | null
  qa_person_name: string | null
  description: string
  classification: DeviationClassification | null
  root_cause_category: RootCauseCategory | null
  quality_impact: QualityImpact | null
  is_repeat: boolean
  capa_initiated: boolean | null
  extension_count: number
  closed_at: string | null
  created_at: string
  updated_at: string
}

export interface RepeatCandidate {
  id: string
  deviation_no: string
  status: DeviationStatus
  discovery_date: string
  description: string
}

export interface DeviationDetail extends DeviationBrief {
  emergency_measures: string | null
  remark: string | null
  department_id: string | null
  m1e_personnel: string | null
  m1e_machine: string | null
  m1e_material: string | null
  m1e_method: string | null
  m1e_environment: string | null
  m1e_other: string | null
  direct_cause: string | null
  root_cause: string | null
  why_chain: WhyStep[]
  extended_investigation: boolean
  extended_result: string | null
  quality_impact_reason: string | null
  stability_needed: boolean
  stability_note: string | null
  validation_impact: boolean
  validation_note: string | null
  registration_impact: boolean
  registration_note: string | null
  notify_customer: boolean
  customer_note: string | null
  repeat_deviation_ids: string[]
  capa_not_initiated_reason: string | null
  investigating_at: string | null
  assessing_at: string | null
  items: DeviationItem[]
  hypothesis_tests: DeviationHypothesisTest[]
  logs: StatusLog[]
  attachments: DeviationAttachment[]
  capas: CapaBrief[]
  repeat_candidates: RepeatCandidate[]
  /** 进入下一阶段前仍缺的必填项（中文标签）。 */
  missing_for_next: string[]
}

export interface DeviationCreateInput {
  discovery_date: string
  occurrence_date?: string | null
  due_date?: string | null
  department_id?: string | null
  department_name?: string | null
  group_name?: string | null
  reporter_name?: string | null
  qa_person_name?: string | null
  description: string
  emergency_measures?: string | null
  remark?: string | null
  items?: DeviationItem[]
}

export type DeviationUpdateInput = Partial<
  Omit<DeviationCreateInput, 'due_date'> & {
    m1e_personnel: string | null
    m1e_machine: string | null
    m1e_material: string | null
    m1e_method: string | null
    m1e_environment: string | null
    m1e_other: string | null
    direct_cause: string | null
    root_cause: string | null
    root_cause_category: RootCauseCategory | null
    why_chain: WhyStep[]
    extended_investigation: boolean
    extended_result: string | null
    hypothesis_tests: DeviationHypothesisTest[]
    quality_impact: QualityImpact | null
    quality_impact_reason: string | null
    classification: DeviationClassification | null
    stability_needed: boolean
    stability_note: string | null
    validation_impact: boolean
    validation_note: string | null
    registration_impact: boolean
    registration_note: string | null
    notify_customer: boolean
    customer_note: string | null
    is_repeat: boolean
    repeat_deviation_ids: string[]
    capa_initiated: boolean | null
    capa_not_initiated_reason: string | null
  }
>

export interface DeviationListParams {
  keyword?: string
  status?: DeviationStatus | ''
  classification?: DeviationClassification | ''
  root_cause_category?: RootCauseCategory | ''
  department_name?: string
  is_repeat?: boolean
  overdue_only?: boolean
  discovery_from?: string
  discovery_to?: string
  page?: number
  page_size?: number
}

// ───────────────────────── AI 辅助 ─────────────────────────

export type DeviationAiAssistKind = 'describe' | 'm1e' | 'why' | 'hypothesis'

/** 偏差 AI 辅助请求：携带当前表单快照，服务端只产建议不落库。 */
export interface DeviationAiAssistInput {
  kind: DeviationAiAssistKind
  deviation_id?: string
  description: string
  department_name?: string | null
  group_name?: string | null
  reporter_name?: string | null
  emergency_measures?: string | null
  items?: DeviationItem[]
  m1e_personnel?: string | null
  m1e_machine?: string | null
  m1e_material?: string | null
  m1e_method?: string | null
  m1e_environment?: string | null
  m1e_other?: string | null
  direct_cause?: string | null
  root_cause?: string | null
  why_chain?: WhyStep[]
  hypothesis_tests?: DeviationHypothesisTest[]
}

export interface DeviationAiMasterMatch {
  master_id: string
  code: string
  name: string
  object_type: string
  match_type: 'exact_code' | 'exact_name' | 'exact_alias' | 'fuzzy'
  confidence: number
}

export interface DeviationAiSuggestedItem {
  category: DeviationItemCategory
  name: string
  batch_no: string | null
  evidence: string | null
  match: DeviationAiMasterMatch | null
}

/** 四种 kind 的响应字段按需出现（kind 之外还有 prompt_version/model）。 */
export interface DeviationAiAssistResult {
  kind: DeviationAiAssistKind
  prompt_version: string
  model: string
  description?: string
  missing_elements?: string[]
  items?: DeviationAiSuggestedItem[]
  checklists?: Partial<Record<'personnel' | 'machine' | 'material' | 'method' | 'environment' | 'other', string[]>>
  steps?: WhyStep[]
  hypotheses?: Array<Pick<DeviationHypothesisTest, 'hypothesis' | 'sample' | 'protocol' | 'expected'>>
}

// ───────────────────────── CAPA ─────────────────────────

export type CapaStatus = 'planned' | 'in_progress' | 'completed' | 'effect_evaluating' | 'closed'
export type CapaSeverity = 'minor' | 'major' | 'critical'
export type CapaActionType = 'corrective' | 'preventive'
export type CapaActionStatus = 'pending' | 'in_progress' | 'done'
export type EffectMethod = 'tracking_week' | 'tracking_batches' | 'tracking_month' | 'custom'
export type EffectConclusion = 'effective' | 'ineffective'
export type CapaTransitionAction = 'start' | 'complete' | 'start_evaluation' | 'close'

export interface CapaActionItem {
  id?: string
  content: string
  action_type: CapaActionType
  department_name?: string | null
  owner_name?: string | null
  planned_date?: string | null
  actual_date?: string | null
  status: CapaActionStatus
  note?: string | null
}

export interface CapaBrief {
  id: string
  capa_no: string
  deviation_id: string
  parent_capa_id: string | null
  severity: CapaSeverity
  status: CapaStatus
  summary: string
  responsible_department_name: string | null
  planned_completion_date: string | null
  is_overdue: boolean
  effect_method: EffectMethod | null
  effect_due_date: string | null
  effect_conclusion: EffectConclusion | null
  completed_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
  /** 台账列表附带的来源偏差编号。 */
  deviation_no?: string | null
}

export interface CapaDetail extends CapaBrief {
  effect_plan: string | null
  effect_result: string | null
  evaluated_at: string | null
  remark: string | null
  in_progress_at: string | null
  evaluating_at: string | null
  deviation: {
    id: string
    deviation_no: string
    status: DeviationStatus
    description: string
    department_name: string | null
  } | null
  parent_capa_no: string | null
  follow_up_capas: { id: string; capa_no: string; status: CapaStatus }[]
  actions: CapaActionItem[]
  logs: StatusLog[]
}

export interface CapaCreateInput {
  deviation_id: string
  parent_capa_id?: string | null
  severity: CapaSeverity
  summary: string
  responsible_department_name?: string | null
  planned_completion_date?: string | null
  effect_method?: EffectMethod | null
  effect_plan?: string | null
  effect_due_date?: string | null
  remark?: string | null
  actions?: CapaActionItem[]
}

export type CapaUpdateInput = Partial<
  Omit<CapaCreateInput, 'deviation_id' | 'parent_capa_id'> & {
    effect_result: string | null
    effect_conclusion: EffectConclusion | null
  }
>

export interface CapaActionPatchInput {
  status?: CapaActionStatus
  actual_date?: string | null
  note?: string | null
  owner_name?: string | null
  planned_date?: string | null
}

export interface CapaListParams {
  keyword?: string
  status?: CapaStatus | ''
  severity?: CapaSeverity | ''
  deviation_id?: string
  page?: number
  page_size?: number
}

// ───────────────────────── 展示文案 ─────────────────────────

export const DEVIATION_STATUS_LABEL: Record<DeviationStatus, string> = {
  draft: '登记中',
  investigating: '调查中',
  assessing: '评估中',
  closed: '已关闭',
}

export const DEVIATION_CLASSIFICATION_LABEL: Record<DeviationClassification, string> = {
  minor: '微小偏差',
  moderate: '中等偏差',
  critical: '关键偏差',
}

export const ROOT_CAUSE_CATEGORY_LABEL: Record<RootCauseCategory, string> = {
  personnel: '人员偏差',
  equipment: '设备/仪器偏差',
  material: '物料偏差',
  method: '方法/程序偏差',
  environment: '环境偏差',
  other: '其他',
}

export const QUALITY_IMPACT_LABEL: Record<QualityImpact, string> = {
  affected: '影响',
  not_affected: '不影响',
}

export const DEVIATION_ITEM_CATEGORY_LABEL: Record<DeviationItemCategory, string> = {
  material: '物料',
  intermediate: '中间体',
  finished: '成品',
  in_process: '中控',
  equipment: '设施设备',
  document: '文件',
  other: '其他',
}

export const DEVIATION_ACTION_LABEL: Record<string, string> = {
  create: '登记偏差',
  start_investigation: '开始调查',
  submit_assessment: '提交评估',
  close: '关闭偏差',
  extend: '延长期限',
  start: '开始实施',
  complete: '措施完成',
  start_evaluation: '进入有效性评估',
}

export const CAPA_STATUS_LABEL: Record<CapaStatus, string> = {
  planned: '已发起',
  in_progress: '实施中',
  completed: '措施完成',
  effect_evaluating: '有效性评估中',
  closed: '已关闭',
}

export const CAPA_SEVERITY_LABEL: Record<CapaSeverity, string> = {
  minor: '次要',
  major: '重要',
  critical: '关键',
}

export const CAPA_ACTION_TYPE_LABEL: Record<CapaActionType, string> = {
  corrective: '纠正措施',
  preventive: '预防措施',
}

export const CAPA_ACTION_STATUS_LABEL: Record<CapaActionStatus, string> = {
  pending: '待开始',
  in_progress: '进行中',
  done: '已完成',
}

export const EFFECT_METHOD_LABEL: Record<EffectMethod, string> = {
  tracking_week: '连续跟踪 1 周',
  tracking_batches: '跟踪至少 3 批',
  tracking_month: '跟踪 1 个月',
  custom: '自定义周期',
}

export const EFFECT_CONCLUSION_LABEL: Record<EffectConclusion, string> = {
  effective: '有效',
  ineffective: '无效',
}
