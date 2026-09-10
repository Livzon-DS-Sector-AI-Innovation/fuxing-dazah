// ==================== 职业健康管理（Occupational Health）====================
//
// 字段名与 `dazah-backend/app/modules/safety/schemas/oh_*.py` 实际 schema 对齐
// （后端为权威源，design.md §六 的占位字段名以实际为准）。
// 监测（HazardMonitor）相关类型已整体废弃删除；旧体检工作流（exam_items/
// abnormality_records 内嵌子记录）由新模型取代。
//
// 枚举命名对照（design §6.1 / ticket 12）：
//   OhFlowStatus        → OhDiffAnalyzeStatus（后端 OhDiffAnalyzeStatus: none/parsing/analyzed/failed）
//   OhSyncFlag          → OhWorkStatus（后端 OhWorkStatus: on_post/off_post/pre_employment/transfer）
//   OhHazardStatus      → OhHazardFactorsStatus（后端: filled/empty/inferred）
//   OhAbnormalLevel     → 后端 OhAbnormalLevel（mild/moderate/severe，异常指标 severity 同值域）

// ── 枚举 ──

export enum OhExamType {
  PRE_EMPLOYMENT = 'pre_employment',
  PERIODIC = 'periodic',
  POST_EMPLOYMENT = 'post_employment',
  TRANSFER = 'transfer',
  EMERGENCY = 'emergency',
}

/** 机器状态（兼容保留，§13.3） */
export enum OhExamStatus {
  PENDING = 'pending',
  SCHEDULED = 'scheduled',
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  ARCHIVED = 'archived',
}

export enum OhAiConclusion {
  NORMAL = 'normal',
  ABNORMAL_OTHER = 'abnormal_other',
  CONTRAINDICATED = 'contraindicated',
  SUSPECTED_OD = 'suspected_od',
  OD_DIAGNOSED = 'od_diagnosed',
  RE_EXAMINATION = 're_examination',
}

export enum OhAiParseStatus {
  PENDING = 'pending',
  PARSING = 'parsing',
  PARSED = 'parsed',
  FAILED = 'failed',
}

export enum OhFitness {
  FIT = 'fit',
  FIT_WITH_RESTRICTION = 'fit_with_restriction',
  UNFIT = 'unfit',
}

/** 在岗状态（原「最后体检状态」更名，D6；后端 OhWorkStatus） */
export enum OhWorkStatus {
  ON_POST = 'on_post',
  OFF_POST = 'off_post',
  PRE_EMPLOYMENT = 'pre_employment',
  TRANSFER = 'transfer',
}

/** 转岗/离岗类型 */
export enum OhTransferType {
  TRANSFER = 'transfer',
  POST_EMPLOYMENT = 'post_employment',
}

/** 申请状态（Bitable 7 态原文值，中文） */
export enum OhApplicationStatus {
  APPROVED = '已通过',
  REVIEWING = '审批中',
  REJECTED = '已拒绝',
  CANCELLED = '已取消',
  TERMINATED = '已终止',
  WITHDRAWN = '已撤回',
  DELETED = '已删除',
}

/** 差异分析状态（后端 OhDiffAnalyzeStatus） */
export enum OhDiffAnalyzeStatus {
  NONE = 'none',
  PARSING = 'parsing',
  ANALYZED = 'analyzed',
  FAILED = 'failed',
}

export enum OhFollowupStatus {
  OPEN = 'open',
  FOLLOWED = 'followed',
  CLOSED = 'closed',
  EXPIRED = 'expired',
}

export enum OhFollowupType {
  RE_EXAMINATION = 're_examination',
  SPECIALIST_REFERRAL = 'specialist_referral',
  TRANSFER_POST = 'transfer_post',
  HEALTH_MONITOR = 'health_monitor',
}

/** 异常指标类别 */
export enum OhFollowupCategory {
  LAB = 'lab',
  VISION = 'vision',
  HEARING = 'hearing',
  PHYSIQUE = 'physique',
  OTHER = 'other',
}

/** 异常程度（指标 severity 同值域） */
export enum OhAbnormalLevel {
  MILD = 'mild',
  MODERATE = 'moderate',
  SEVERE = 'severe',
}

/** 岗位危害因素状态 */
export enum OhHazardFactorsStatus {
  FILLED = 'filled',
  EMPTY = 'empty',
  INFERRED = 'inferred',
}

// ── 实体接口 ──

/** 人员汇总台账（一人一条；详情含体检链 + 异常随访展开） */
export interface OhPerson {
  id: string
  feishu_record_id?: string
  source?: string
  name: string
  id_card_no?: string
  employee_no?: string
  user_id?: string | null
  open_id?: string
  department?: string
  position?: string
  gender?: string
  age?: number
  marital_status?: string
  phone?: string
  total_work_years?: number
  hazard_exposure_years?: number
  hazard_factors?: string[] // 标准名列表（42 项字典）
  last_exam_at?: string
  last_exam_type?: OhExamType
  last_exam_conclusion?: OhAiConclusion | string
  last_exam_summary?: string
  exam_record_ids?: string[] // 体检记录 ID 数组（列表链接「X 条」取 length）
  safety_officer?: string
  work_status?: OhWorkStatus
  notes?: string
  exams?: OhHealthExam[] // 详情展开：体检记录链
  followups?: OhFollowup[] // 详情展开：异常随访
  created_at: string
  updated_at: string
}

/** 职业健康体检记录（一人多条；详情含 ai_parse_result + followups） */
export interface OhHealthExam {
  id: string
  feishu_record_id?: string
  source?: string
  exam_no?: string
  person_id?: string | null
  employee_name: string
  id_card_no?: string
  employee_no?: string
  department?: string
  position?: string
  gender?: string
  age?: number
  marital_status?: string
  phone?: string
  exam_type: OhExamType
  exam_agency?: string
  scheduled_date?: string
  exam_date?: string
  report_date?: string
  hazard_factors?: string[] // 标准名列表
  protection_measures?: string
  total_work_years?: number
  hazard_exposure_years?: number
  exam_result?: string // 体检结果（AI 输入①原文）
  exam_conclusion?: string // 检查结论（AI 输入①原文）
  treatment_advice_raw?: string // 处理意见原文
  paper_report_kept?: string
  synced_to_summary?: boolean // 是否已同步汇总表
  source_table?: string
  source_record_id?: string
  attachments?: Array<{ name?: string; path?: string }>
  attachment_paths?: string[]
  status: OhExamStatus
  // AI 字段（平台独占）
  ai_parse_status: OhAiParseStatus
  ai_parse_error?: string
  ai_parse_result?: OhExamReportParseOutput | null
  ai_interpretation?: string // 「AI智能解读」文本（存量记录降级展示）
  ai_conclusion?: OhAiConclusion
  ai_contraindication_factors?: string[]
  ai_fitness?: OhFitness
  ai_override_notes?: string // 人工覆盖结论备注（留痕）
  override_conclusion?: OhAiConclusion // 非空表示已人工覆盖
  override_by?: string | null
  override_at?: string
  notes?: string
  followups?: OhFollowup[] // 详情展开
  created_at: string
  updated_at: string
}

/** 岗位危害台账 */
export interface OhPosition {
  id: string
  feishu_record_id?: string
  source?: string
  department?: string
  position?: string
  job_title?: string
  hazard_factors?: string[]
  hazard_factors_status?: OhHazardFactorsStatus
  notes?: string
  created_at: string
  updated_at: string
}

/** 危害因素 PPE 映射字典 */
export interface OhHazardFactor {
  id: string
  feishu_record_id?: string
  source?: string
  factor_name: string
  ppe_respiratory?: string // 呼吸防护用品
  notes?: string
  created_at: string
  updated_at: string
}

/** 转岗/离岗体检申请 */
export interface OhExamApplication {
  id: string
  feishu_record_id?: string
  source?: string
  application_no?: string
  apply_status?: OhApplicationStatus
  approval_flow?: string // 审批流程名称
  approval_node?: string // 当前审批节点
  current_handler?: string // 当前处理人
  initiator_name?: string // 发起人姓名
  submitted_at?: string // 发起时间
  completed_at?: string // 完成时间
  transfer_type?: OhTransferType
  exam_type?: string // 体检类型: 离岗体检/转岗体检（Bitable 原文）
  employee_name?: string
  id_card_no?: string
  department?: string // 原部门
  position?: string // 原岗位
  new_department?: string // 转入部门
  new_position?: string // 转入岗位
  transfer_date?: string // 转岗日期
  leave_date?: string // 离岗日期
  dept_safety_officer?: string // 部门安全员
  applicant_name?: string // 申请人
  apply_date?: string // 申请日期
  // AI 差异分析
  diff_analyze_status: OhDiffAnalyzeStatus
  diff_analyze_error?: string
  diff_analyze_result?: OhTransferDiffOutput | null
  diff_summary?: string
  needs_exam?: boolean
  exam_suggestion?: string // 建议体检类型（中文标签或枚举值）
  created_exam_id?: string | null // 自动创建的体检登记
  bt_extra?: Record<string, unknown> // Bitable 脏字段兜底
  notes?: string
  created_at: string
  updated_at: string
}

/** 审批节点（审批 Timeline 数据；后端以 approval_node/approval_flow/bt_extra 提供） */
export interface OhApprovalNode {
  node_name: string
  handler?: string
  result?: string
  processed_at?: string
}

/** 异常随访 */
export interface OhFollowup {
  id: string
  exam_id?: string | null
  person_id?: string | null
  person_name?: string
  indicator_name?: string
  indicator_value?: string
  reference_range?: string
  abnormal_level?: OhAbnormalLevel
  category?: OhFollowupCategory
  followup_type?: OhFollowupType
  followup_date?: string // 建议复查/处置日期
  status: OhFollowupStatus
  action_taken?: string // 处置记录
  responsible?: string // 责任人
  closed_at?: string
  source: 'ai' | 'manual'
  notes?: string
  created_at: string
  updated_at: string
}

/** 异常指标（AI 输出子项） */
export interface OhAbnormalIndicator {
  name: string
  value: string // 保留原文单位与 ↑↓ 标记
  reference_range?: string | null
  category: OhFollowupCategory | string
  severity: OhAbnormalLevel | string
  followup_suggestion?: string | null
}

// ── AI 输出（对齐后端 oh_ai.py / oh_transfer.py）──

/** 体检报告智能解析全量输出（对应 oh_health_exams.ai_parse_result） */
export interface OhExamReportParseOutput {
  abnormal_indicators: OhAbnormalIndicator[]
  conclusion_category: OhAiConclusion | string
  contraindication_factors: string[]
  contraindication_statement?: string | null
  has_contraindication: boolean
  fitness: OhFitness | string
  treatment_advice: string[]
  recommendations: string[]
  summary_text: string
}

/** 转岗/离岗危害差异分析输出（对应 diff_analyze_result） */
export interface OhTransferDiffOutput {
  added_hazards: string[]
  removed_hazards: string[]
  new_ppe_required: Array<{ factor: string; ppe: string }>
  key_followup_items: string[]
  needs_exam: boolean
  exam_type_suggestion: OhExamType | string
  health_advice: string
  summary: string
}

// ── 统计 ──

/** 人员台账统计（后端 OhPersonStats） */
export interface OhPersonStats {
  total: number
  hazard_exposed: number
  by_department?: Record<string, number>
  by_position?: Record<string, number>
  by_work_status?: Record<string, number>
  by_last_exam_conclusion?: Record<string, number>
}

/** 体检统计（后端 OhStats） */
export interface OhExamStats {
  total: number
  abnormal: number
  contraindicated: number
  pending_parse: number
  by_category?: Record<string, number>
}

/** 申请统计（后端 get_stats） */
export interface OhApplicationStats {
  total: number
  by_status?: Record<string, number>
  needs_exam: number
}

/** 随访统计（无后端端点，KPI 由列表查询客户端派生） */
export interface OhFollowupStats {
  total: number
  open: number
  followed: number
  overdue: number
}

// ── QueryParams ──

export interface OhPersonQueryParams {
  page?: number
  page_size?: number
  department?: string
  position?: string
  hazard_exposure?: string // 'yes'
  last_exam_conclusion?: string
  keyword?: string
}

export interface OhHealthExamQueryParams {
  page?: number
  page_size?: number
  status?: OhExamStatus | string
  exam_type?: OhExamType | string
  department?: string
  ai_conclusion?: OhAiConclusion | string
  ai_parse_status?: OhAiParseStatus | string
  keyword?: string
}

export interface OhPositionQueryParams {
  page?: number
  page_size?: number
  department?: string
  hazard_factors_status?: OhHazardFactorsStatus | string
}

export interface OhHazardFactorQueryParams {
  page?: number
  page_size?: number
}

export interface OhExamApplicationQueryParams {
  page?: number
  page_size?: number
  status?: OhApplicationStatus | string
  transfer_type?: OhTransferType | string
  keyword?: string
}

export interface OhFollowupQueryParams {
  page?: number
  page_size?: number
  status?: OhFollowupStatus | string
  category?: OhFollowupCategory | string
  person_id?: string
  due_order?: boolean
}

// ── FormData ──

/** 创建体检记录（后端 OhHealthExamCreate；exam_type/employee_name 必填） */
export interface OhHealthExamFormData {
  exam_no?: string
  person_id?: string
  employee_name: string
  id_card_no?: string
  employee_no?: string
  department?: string
  position?: string
  gender?: string
  age?: number
  marital_status?: string
  phone?: string
  exam_type: OhExamType | string
  exam_agency?: string
  scheduled_date?: string
  exam_date?: string
  report_date?: string
  hazard_factors?: string[]
  protection_measures?: string
  total_work_years?: number
  hazard_exposure_years?: number
  exam_result?: string
  exam_conclusion?: string
  treatment_advice_raw?: string
  paper_report_kept?: string
  synced_to_summary?: boolean
  source?: string
  notes?: string
}

/** 手动补录随访（后端 OhFollowupCreate；exam_id 或 person_id 必填其一） */
export interface OhFollowupFormData {
  exam_id?: string
  person_id?: string
  person_name?: string
  indicator_name?: string
  indicator_value?: string
  reference_range?: string
  abnormal_level?: OhAbnormalLevel | string
  category?: OhFollowupCategory | string
  followup_type?: OhFollowupType | string
  followup_date?: string
  status?: OhFollowupStatus | string // 处置更新用（open→followed 状态机，后端 OhFollowupUpdate）
  action_taken?: string
  responsible?: string
  notes?: string
}

/** 人工覆盖体检结论请求（后端 OverrideConclusionRequest） */
export interface OhOverrideConclusionRequest {
  override_conclusion: OhAiConclusion | string
  notes?: string
}
