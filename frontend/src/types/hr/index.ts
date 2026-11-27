export interface Employee {
  id: string
  employee_number: string
  name: string
  domain_account?: string
  department: string
  position: string
  duty?: string
  report_grade?: string
  job_category?: string
  certificates?: string
  level?: string
  gender?: string
  native_place?: string
  ethnicity?: string
  marital_status?: string
  household_type?: string
  status_category?: string
  hr_analysis?: string
  birth_year?: number
  birth_month?: number
  birth_day?: number
  work_start_date?: string
  hire_date: string
  graduation_date?: string
  departure_date?: string
  departure_reason?: string
  company_tenure?: string
  education?: string
  classification?: string
  school?: string
  major?: string
  degree_type?: string
  graduation_certificate?: string
  id_card?: string
  id_card_expiry?: string
  current_address?: string
  contract_start_date?: string
  contract_end_date?: string
  phone?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  transfer_history?: string
  status: string
  feishu_record_id?: string
  feishu_synced_at?: string
  /** 是否重点岗位（影响试用期时长/安全考试节点/应交证件清单） */
  is_key_position?: boolean | null
  /** 直属上级姓名（转正评估第一级审批人） */
  direct_manager_name?: string | null
  /** 来源候选人（招聘入职回链），可用于跳转候选人详情页 */
  candidate_id?: string
  created_at?: string
  updated_at?: string
  /** 从出生日期动态计算的年龄（优先于飞书静态值） */
  computed_age?: number
  /** 从入职日期动态计算的司龄，格式如"3年5个月" */
  computed_tenure?: string
  /** 转正到期日（试用期员工；显式值优先否则入职+3月-1天） */
  computed_probation_end?: string
  /** 距转正到期天数（负数=已过期；非试用期为空） */
  computed_probation_days_left?: number
}

export interface EmployeeCreateInput {
  employee_number: string
  name: string
  domain_account?: string
  department: string
  position: string
  job_category?: string
  level?: string
  gender?: string
  native_place?: string
  ethnicity?: string
  marital_status?: string
  household_type?: string
  status_category?: string
  hr_analysis?: string
  birth_year?: number
  birth_month?: number
  birth_day?: number
  work_start_date?: string
  hire_date: string
  graduation_date?: string
  education?: string
  classification?: string
  school?: string
  major?: string
  degree_type?: string
  graduation_certificate?: string
  id_card?: string
  id_card_expiry?: string
  current_address?: string
  contract_start_date?: string
  contract_end_date?: string
  phone?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  transfer_history?: string
  status?: string
}

export interface EmployeeUpdateInput {
  employee_number?: string
  name?: string
  domain_account?: string
  department?: string
  position?: string
  job_category?: string
  level?: string
  gender?: string
  native_place?: string
  ethnicity?: string
  marital_status?: string
  household_type?: string
  status_category?: string
  hr_analysis?: string
  birth_year?: number
  birth_month?: number
  birth_day?: number
  work_start_date?: string
  hire_date?: string
  graduation_date?: string
  education?: string
  classification?: string
  school?: string
  major?: string
  degree_type?: string
  graduation_certificate?: string
  id_card?: string
  id_card_expiry?: string
  current_address?: string
  contract_start_date?: string
  contract_end_date?: string
  phone?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  transfer_history?: string
  status?: string
  probation_end_date?: string | null
  regularization_date?: string
  departure_date?: string
  departure_reason?: string
}

export interface EmployeeListResponse {
  code: number
  message: string
  data: Employee[]
  meta?: {
    page: number
    page_size: number
    total: number
  }
}

/** 员工筛选面板：各可枚举字段的现有取值（后端聚合，跟随数据变化） */
export interface EmployeeFilterOptions {
  department?: string[]
  position?: string[]
  duty?: string[]
  job_category?: string[]
  level?: string[]
  report_grade?: string[]
  status_category?: string[]
  gender?: string[]
  ethnicity?: string[]
  native_place?: string[]
  marital_status?: string[]
  household_type?: string[]
  education?: string[]
  degree_type?: string[]
  classification?: string[]
  school?: string[]
  major?: string[]
  hr_analysis?: string[]
}

/**
 * 员工档案字段级筛选（筛选面板状态）：
 * 下拉/文本为单值；日期范围为 [起, 止]（YYYY-MM-DD）；出生年份为 [起年, 止年]。
 */
export interface EmployeeFieldFilters {
  position?: string
  duty?: string
  job_category?: string
  level?: string
  report_grade?: string
  status_category?: string
  gender?: string
  ethnicity?: string
  native_place?: string
  marital_status?: string
  household_type?: string
  education?: string
  degree_type?: string
  classification?: string
  school?: string
  major?: string
  hr_analysis?: string
  domain_account?: string
  departure_reason?: string
  age_min?: number
  age_max?: number
  birth_year?: [number, number]
  graduation_date?: [string, string]
  work_start_date?: [string, string]
  hire_date?: [string, string]
  departure_date?: [string, string]
  contract_start_date?: [string, string]
  contract_end_date?: [string, string]
}

/**
 * 员工列表/导出共用的筛选参数（导出与列表同口径，保证所见即所得）。
 * 住在 types 而非 actions：client 侧工具（lib/hr/employeeFilters）需要引用它，
 * 从 'use server' 模块引类型会让 turbopack 的 client 依赖图触碰 server action 边界。
 */
export interface EmployeeFilterParams {
  department?: string
  status?: string
  keyword?: string
  /** 仅「未归类」人员（部门为空或不在部门表中）；对应档案页独立的「未归类」页签 */
  uncategorized_only?: boolean
  // ── 字段级筛选（档案筛选面板；下拉精确匹配，选项来自 filter-options）──
  position?: string
  duty?: string
  job_category?: string
  level?: string
  report_grade?: string
  status_category?: string
  gender?: string
  ethnicity?: string
  native_place?: string
  marital_status?: string
  household_type?: string
  education?: string
  degree_type?: string
  classification?: string
  school?: string
  major?: string
  hr_analysis?: string
  domain_account?: string
  departure_reason?: string
  age_min?: number
  age_max?: number
  birth_year_min?: number
  birth_year_max?: number
  hire_date_after?: string
  hire_date_before?: string
  work_start_date_after?: string
  work_start_date_before?: string
  graduation_date_after?: string
  graduation_date_before?: string
  departure_date_after?: string
  departure_date_before?: string
  contract_start_date_after?: string
  contract_start_date_before?: string
  contract_end_date_after?: string
  contract_end_date_before?: string
}

/** 员工异动记录（晋升/转岗/产假复岗等，档案页行内「异动记录」维护） */
export interface EmployeeTransfer {
  id?: string
  employee_id?: string
  transfer_type: string
  from_department?: string | null
  to_department?: string | null
  from_position?: string | null
  to_position?: string | null
  effective_date: string
  reason?: string | null
}

/** 离职台账筛选下拉选项（部门/离职类型现有取值，后端聚合） */
export interface DepartureFilterOptions {
  departments?: string[]
  offboarding_types?: string[]
}

/** 入职台账筛选下拉选项（入职年份现有取值，后端聚合） */
export interface OnboardingFilterOptions {
  years?: number[]
}

/** 入职培训下拉候选（与入职台账列表同源：员工档案 + 在职） */
export interface TrainingCandidate {
  id: string
  employee_id: string
  employee_number: string
  name: string
  department: string
  position: string
  hire_date: string | null
  education: string | null
  school: string | null
  graduation_date: string | null
  /** 入职台账记录来源；无台账记录时为「新入职」 */
  source: string
  /** 已完成入职培训：最近一次职位变动生效日期之后存在入职培训记录表导出写入的记录 */
  prejob_completed: boolean
  /** 职位变动记录（晋升/转岗/产假复岗），按生效日期降序，[0] 为最近一次 */
  transfers: EmployeeTransfer[]
}

/** 部门下的培训岗位及其培训大类（岗位培训关联表与 SOP 目录取并集） */
export interface DepartmentTrainingPosition {
  position_name: string
  categories: {
    training_category: string
    trainer: string | null
    training_method: string | null
  }[]
}

export interface EmployeeResponse {
  code: number
  message: string
  data: Employee
}

export interface SyncStatusResponse {
  code: number
  message: string
  data: {
    local_total: number
    feishu_total: number
    synced_count: number
    unsynced_count: number
    conflict_count: number
    last_sync_at: string | null
  }
}

/** 部门负责人 / 分管领导的账号就绪状态（能否按姓名解析到飞书账号，与后端 department_manager_status 对齐）：
 *  ok 就绪 / no_account 未登录过系统（收不到）/ ambiguous 同名多账号（不会发）/ left 已离职（会发给已离职的人） */
export type ManagerAccountStatus = 'ok' | 'no_account' | 'ambiguous' | 'left'

export interface Department {
  id: string
  name: string
  code: string
  description?: string
  /** 部门负责人（劳动合同续签审批提醒接收人；转正审批第二级） */
  department_manager_name?: string | null
  /** 分管领导（转正审批第三级） */
  supervising_leader_name?: string | null
  /** 账号就绪状态；没填姓名时为空串 */
  manager_account_status?: ManagerAccountStatus | ''
  leader_account_status?: ManagerAccountStatus | ''
  employee_count?: number
  created_at?: string
  updated_at?: string
}

export interface DepartmentCreateInput {
  name: string
  code: string
  description?: string
}

export interface DepartmentUpdateInput {
  name?: string
  code?: string
  description?: string
  /** 传 null 表示清空（undefined 会被 JSON.stringify 丢弃，后端按「不更新」处理） */
  department_manager_name?: string | null
  supervising_leader_name?: string | null
}

export interface DepartmentListResponse {
  code: number
  message: string
  data: Department[]
  meta?: {
    page: number
    page_size: number
    total: number
  }
}

export interface OnboardingRecord {
  id: string
  seq_number?: number
  employee_number: string
  name: string
  domain_account?: string
  department: string
  team?: string
  position: string
  job_category?: string
  status_category?: string
  is_employed?: string
  hire_date: string
  factory_entry_date?: string
  livo_entry_date?: string
  work_start_date?: string
  graduation_date?: string
  birth_month?: number
  birth_day?: number
  contract_type?: string
  contract_start_date?: string
  contract_end_date?: string
  contract_start_2?: string
  contract_end_2?: string
  contract_start_3?: string
  contract_end_3?: string
  contract_start_4?: string
  contract_end_4?: string
  age?: number
  work_years?: number
  factory_tenure?: string
  company_tenure?: string
  hire_month?: string
  school?: string
  education?: string
  major?: string
  classification?: string
  id_card?: string
  id_card_expiry?: string
  id_card_address?: string
  current_address?: string
  marital_status?: string
  household_type?: string
  political_status?: string
  phone?: string
  email?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  bank_account?: string
  bank_account_location?: string
  training_id?: string
  transfer_history?: string
  remarks?: string[]
  feishu_record_id?: string
  feishu_synced_at?: string
  created_at?: string
  updated_at?: string
}

export interface OnboardingRecordListResponse {
  code: number
  message: string
  data: OnboardingRecord[]
  meta?: {
    page: number
    page_size: number
    total: number
  }
}

export interface DepartureRecord {
  id: string
  name: string
  /** 工号（飞书离职人员管理表同步） */
  employee_number?: string
  department: string
  team?: string
  position: string
  duty?: string
  rank?: string
  rank_category?: string
  job_category?: string
  /** 员工性质（转正员工/退休返聘等） */
  employee_category?: string
  gender?: string
  status_category?: string
  livo_entry_date?: string
  factory_entry_date?: string
  work_start_date?: string
  offboarding_date: string
  company_tenure_at_leave?: string
  education?: string
  school?: string
  major?: string
  degree_type?: string
  classification?: string
  id_card?: string
  id_card_expiry?: string
  native_place?: string
  ethnicity?: string
  household_type?: string
  marital_status?: string
  political_status?: string
  residence_address?: string
  phone?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  bank_account?: string
  contract_type?: string
  contract_start_date?: string
  contract_end_date?: string
  transfer_history?: string
  offboarding_type: string
  offboarding_reason?: string[]
  offboarding_reason_2?: string[]
  offboarding_remarks?: string[]
  remarks?: string[]
  certificates?: string
  feishu_record_id?: string
  feishu_synced_at?: string
  created_at?: string
  updated_at?: string
  /** 解除劳动关系证明开具时间（离职办理流程回写） */
  cert_issued_at?: string | null
  cert_sign_status?: string
  cert_signed_at?: string
  cert_sign_name?: string
  cert_sign_image?: string
}

export interface DepartureRecordListResponse {
  code: number
  message: string
  data: DepartureRecord[]
  meta?: {
    page: number
    page_size: number
    total: number
  }
}

export interface TrainingLedgerRecord {
  id: string
  employee_number: string
  training_date: string
  training_subject: string
  training_method?: string
  duration_hours?: number
  location?: string
  trainer?: string
  assessment_result?: string
  source_type: string
  source_id?: string
  remarks?: string
  created_at?: string
  updated_at?: string
}

export interface TrainingLedgerCreateInput {
  employee_number: string
  training_date: string
  training_subject: string
  training_method?: string
  duration_hours?: number
  location?: string
  trainer?: string
  assessment_result?: string
  source_type?: string
  source_id?: string
  remarks?: string
}

export interface TrainingLedgerUpdateInput {
  employee_number?: string
  training_date?: string
  training_subject?: string
  training_method?: string
  duration_hours?: number
  location?: string
  trainer?: string
  assessment_result?: string
  source_type?: string
  source_id?: string
  remarks?: string
}

export interface TrainingLedgerListResponse {
  code: number
  message: string
  data: TrainingLedgerRecord[]
  meta?: {
    page: number
    page_size: number
    total: number
  }
}

// ─── SOP 培训文件登记表 / 二级表 ───

export interface SopTrainingRecord {
  id: string
  year: string
  training_date: string | null
  file_name: string
  file_no: string | null
  effective_date: string | null
  method: string | null
  /** 考核方式：阅读并理解/问答/笔试；空 = 后端按培训方式取默认（R→阅读并理解，T→问答） */
  assessment_method?: string | null
  /** 合并登记的文件列表；空 = 单文件（看 file_name/file_no） */
  files?: { file_name: string; file_no: string | null }[] | null
  complete_time: string | null
  trainer: string | null
  trainees: string | null
  involved_departments: string[]
  change_note: string | null
  color: string
  status: string
  initiator_department: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface SopTrainingPersonnel {
  employee_number: string
  name: string
}

export interface SopTrainingEntry {
  id: string
  record_id: string | null
  department: string
  file_name: string | null
  file_no: string | null
  method: string | null
  trainer: string | null
  status: string
  complete_time: string | null
  /** 自定义分类，多选按「；」连接（对应创建人员工标签），展示用 splitSopEntryClassifications 拆 */
  classification: string | null
  personnel: SopTrainingPersonnel[]
  personnel_count: number
  generated_by: string | null
  generated_at: string | null
  created_at: string
  updated_at: string
}

export interface SopClassificationOption {
  tag_name: string
  count: number
}

/** 培训效果评估表统计预填（生成材料弹窗）：不合格恒为 0，优秀+合格=参加考核 */
export interface SopEvaluationStats {
  actual_count: number
  exam_count: number
  excellent_count: number
  qualified_count: number
}

/** 生成材料弹窗的统计基数（materials-preview 接口返回） */
export interface SopMaterialsPreview {
  expected_count: number
  sick_leave: number
  maternity_leave: number
}

export interface SopPersonnelOption {
  employee_number: string
  name: string
  position: string
  status: string
}

// ─── 培训人员名单 · 人员分类 ───

/** 人员分类：按创建人隔离，人员通过同名标签归入分类 */
export interface EmployeeClassification {
  id: string
  name: string
  count: number
}

export interface ClassificationMember {
  employee_number: string
  name: string
  department: string
  position: string
}

// ─── AI 出题相关类型 ───

export interface ChoiceOption {
  label: string
  text: string
}

export interface ChoiceQuestion {
  number: number
  question: string
  options: ChoiceOption[]
  answer?: string
}

export interface TrueFalseQuestion {
  number: number
  question: string
  answer?: string
}

export interface ExamGenerateResponse {
  code: number
  message: string
  data: {
    choice_questions: ChoiceQuestion[]
    true_false_questions: TrueFalseQuestion[]
    multi_choice_questions?: ChoiceQuestion[]
    fill_blank_questions?: TrueFalseQuestion[]
  }
}

export interface ExamExportData {
  title: string
  examiner?: string
  exam_date?: string
  assessment_date: string
  choice_questions: ChoiceQuestion[]
  true_false_questions: TrueFalseQuestion[]
  multi_choice_questions?: ChoiceQuestion[]
  fill_blank_questions?: TrueFalseQuestion[]
}

// ─── AnnualTrainingPlan Types ───

export interface AnnualTrainingPlan {
  id: string
  year: number
  department: string
  status: string
  created_at?: string
  updated_at?: string
}

export interface AnnualTrainingPlanCreateInput {
  year: number
  department: string
  status?: string
}

export interface AnnualTrainingPlanUpdateInput {
  year?: number
  department?: string
  status?: string
}

export interface AnnualTrainingPlanListResponse {
  code: number
  message: string
  data: AnnualTrainingPlan[]
  meta?: {
    page: number
    page_size: number
    total: number
  }
}

export interface AnnualTrainingPlanItem {
  id: string
  plan_id: string
  month?: string
  trainee_count?: number
  duration_hours?: number
  content_and_textbook?: string
  target_audience?: string
  position_and_count?: string
  training_method?: string
  training_hours?: number
  confirmer?: string
  confirm_date?: string
  remarks?: string
  tracking_status?: string
  sort_order: number
  created_at?: string
  updated_at?: string
}

export interface AnnualTrainingPlanItemBatchUpdateInput {
  items: Omit<AnnualTrainingPlanItem, 'id' | 'plan_id' | 'created_at' | 'updated_at'>[]
}

// ─── 招聘相关类型 ───

export interface JobRequirement {
  id: string
  position_name: string
  department: string
  headcount: number
  hired_count: number
  requirements?: string
  status: string
  urgency?: string
  owner?: string
  deadline?: string
  created_at?: string
}

export interface JobRequirementCreateInput {
  position_name: string
  department: string
  headcount?: number
  requirements?: string
  urgency?: string
  owner?: string
  deadline?: string
}

export interface JobRequirementUpdateInput {
  position_name?: string
  department?: string
  headcount?: number
  requirements?: string
  status?: string
  urgency?: string
  owner?: string
  deadline?: string
}

export interface Candidate {
  id: string
  name: string
  phone?: string
  email?: string
  position?: string
  department?: string
  gender?: string
  school?: string
  education?: string
  major?: string
  graduation_date?: string
  resume_url?: string
  status?: string
  recommendation_level?: string
  match_report?: string
  job_requirement_id?: string
  candidate_type?: string
  offer_status?: string
  offer_sent_at?: string
  source?: string
  expected_salary?: string
  current_company?: string
  work_years?: number
  notes?: string
  created_at?: string
  updated_at?: string
}

export interface CandidateCreateInput {
  name: string
  phone?: string
  email?: string
  position?: string
  department?: string
  gender?: string
  school?: string
  education?: string
  major?: string
  graduation_date?: string
  resume_url?: string
  status?: string
  recommendation_level?: string
  job_requirement_id?: string
  candidate_type?: string
  source?: string
  expected_salary?: string
  current_company?: string
  work_years?: number
  match_report?: string
  notes?: string
}

export interface CandidateUpdateInput {
  name?: string
  phone?: string
  email?: string
  position?: string
  department?: string
  gender?: string
  school?: string
  education?: string
  major?: string
  status?: string
  recommendation_level?: string
  job_requirement_id?: string
  candidate_type?: string
  offer_status?: string
  source?: string
  expected_salary?: string
  current_company?: string
  work_years?: number
  match_report?: string
  notes?: string
}

export interface CandidateStatusTransition {
  status: string
  remark?: string
}

export interface Interview {
  id: string
  candidate_id: string
  job_requirement_id?: string
  interview_type: string
  interview_date?: string
  start_time?: string
  end_time?: string
  interviewer?: string
  location?: string
  status: string
  transcript_text?: string
  notes?: string
  calendar_event_id?: string
  calendar_sync_error?: string | null
  /** 评分卡推送时间（非空=已推送评分表单卡给面试官，待其飞书内提交） */
  score_pushed_at?: string
  created_at?: string
}

export interface InterviewCreateInput {
  candidate_id: string
  job_requirement_id?: string
  interview_type?: string
  interview_date?: string
  start_time?: string
  end_time?: string
  interviewer?: string
  location?: string
  notes?: string
  create_calendar_event?: boolean
  force_conflict?: boolean
}

export interface InterviewUpdateInput {
  interview_type?: string
  interview_date?: string
  start_time?: string
  end_time?: string
  interviewer?: string
  location?: string
  status?: string
  transcript_text?: string
  notes?: string
  create_calendar_event?: boolean
  force_conflict?: boolean
}

export interface InterviewOverviewItem extends Interview {
  candidate_name?: string | null
  candidate_position?: string | null
  /** 人工面试评价结论（通过/待定/不通过）与四维度均分（1-5） */
  feedback_result?: string | null
  feedback_score?: number | null
  /** AI 胜任度报告综合分（0-100）与推荐等级 */
  ai_total_score?: number | null
  ai_recommend_level?: string | null
}

export interface InterviewFeedbackDimension {
  name: string
  score: number
  comment?: string
}

export interface InterviewFeedback {
  id: string
  interview_id: string
  candidate_id: string
  evaluator: string
  dimensions?: InterviewFeedbackDimension[] | null
  overall_comment?: string | null
  result: string
  created_at?: string
  updated_at?: string
}

export interface InterviewFeedbackInput {
  evaluator: string
  dimensions?: InterviewFeedbackDimension[]
  overall_comment?: string
  result: string
}

export interface AiEvaluation {
  id: string
  candidate_id: string
  job_requirement_id?: string
  interview_id?: string
  jd_match_score?: number
  professional_score?: number
  communication_score?: number
  learning_score?: number
  stability_score?: number
  overall_score?: number
  strengths?: string
  weaknesses?: string
  ai_summary?: string
  risk_flags?: string
  model_version?: string
  evaluated_at?: string
  created_at?: string
}

// ─── 入职子任务 ───

export interface OnboardingTask {
  id: string
  candidate_id: string
  task_type: string
  status: string
  sort_order: number
  completed_at?: string
  completed_by?: string
  notes?: string
  created_at?: string
}

// ─── 招聘统计增强 ───

export interface ConversionRate {
  from: string
  to: string
  rate: number
}

export interface JobProgress {
  id: string
  position_name: string
  department: string
  headcount: number
  hired_count: number
}

export interface RecruitmentStats {
  total_candidates: number
  active_jobs: number
  funnel: Array<{ status: string; count: number }>
  conversion_rates: ConversionRate[]
  avg_cycle_days?: number
  job_progress: JobProgress[]
  monthly_hires?: Array<{ month: string; count: number }>
  source_stats?: Array<{ source: string; count: number }>
}

// ─── 问答/实操考核 ───

export interface QaQuestion {
  file_no: string
  question: string
  answer: string
  score: number
}

export interface QaAssessment {
  id: string
  subject: string
  department?: string | null
  training_date?: string | null
  training_method?: string | null
  assessment_method: string
  trainer?: string | null
  questions?: QaQuestion[] | null
  question_count: number
  full_score: number
  excellent_line: number
  pass_line: number
}

export interface QaAssessmentScore {
  id: string
  employee_name: string
  employee_number?: string | null
  wrong_questions?: number[] | null
  total_score: number
  grade?: string | null
  result_text?: string | null
  assessed_date?: string | null
}

export interface QaAssessmentCreateInput {
  subject: string
  department?: string
  training_date?: string
  training_method?: string
  assessment_method?: string
  trainer?: string
  questions?: QaQuestion[]
  question_count?: number
  full_score?: number
  excellent_line?: number
  pass_line?: number
  trainee_names: string[]
}

export interface QaScoreSaveInput {
  assessed_date?: string
  scores: { employee_name: string; employee_number?: string; wrong_questions: number[] }[]
}

export interface QuestionBankItem {
  id: string
  file_no: string
  subject?: string | null
  question: string
  answer: string
  score: number
  source: string
  department?: string | null
  usage_count: number
  last_used_date?: string | null
}

// ─── 培训文档生成 / 台账页面 / 职位选项（原 lib/hr/api.ts 中的类型） ───

export interface TrainingSignInSheetData {
  training_date: string
  training_time_start?: string
  training_time_end?: string
  department: string
  training_subject?: string
  topic: string
  instructor?: string
  location?: string
  training_method?: string
  assessment_method?: string
  employee_names: string[]
  remarks?: string
}

export interface TrainingNotificationData {
  department: string
  training_date?: string
  training_date_start?: string
  training_date_end?: string
  subject: string
  training_time_start?: string
  training_time_end?: string
  face_to_face_time_start?: string
  face_to_face_time_end?: string
  self_study_time_start?: string
  self_study_time_end?: string
  location?: string
  trainer?: string
  training_method?: string
  assessment_method?: string
  content?: string
  trainee_names: string[]
  issuer_department?: string
  issue_date?: string
}

export interface TrainingLedgerPageRecord {
  id: string
  employee_number: string
  employee_name: string
  department?: string
  created_at: string
  updated_at: string
}

export interface PositionOption {
  id: string
  department: string
  name: string
  categories?: string[]
  headcount: number | null
}

// ─── 月度绩效考核 ───

export interface PerformanceItem {
  id?: string
  category: 'key_work' | 'routine_work' | 'reward_penalty'
  indicator: string
  standard?: string | null
  weight: number
  self_score?: number | null
  leader_score?: number | null
  final_score?: number | null
  completion?: string | null
  sort_order: number
}

export interface PerformanceEvaluation {
  id: string
  department: string
  department_head: string
  evaluator_leader?: string | null
  evaluation_month: string
  headcount?: number | null
  status: 'draft' | 'self_submitted' | 'leader_scored' | 'confirmed'
  self_submitted_at?: string | null
  leader_submitted_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  items: PerformanceItem[]
}

// ─── 仪表盘 ───

/** KPI 悬停人员明细（姓名 + 部门） */
export interface DashboardPersonItem {
  name: string
  department: string
}

export interface DashboardSummary {
  total_employees: number
  new_hires_this_month: number
  new_hires_this_month_detail?: DashboardPersonItem[]
  departures_this_month: number
  departures_this_month_detail?: DashboardPersonItem[]
  today_hires: number
  today_hires_detail?: DashboardPersonItem[]
  today_departures: number
  today_departures_detail?: DashboardPersonItem[]
  age_avg: number
  probation_count: number
  avg_tenure: number
  net_growth_this_month: number
  passive_departures: number
  contract_expiry_90: number
  quota_total: number
  quota_rate: number
  work_injury_count: number
  labor_dispute_count: number
  underperforming_count: number
  interviews_today: number
  interviews_this_week: number
  performance_submitted_count: number
  active_departure_rate: number
  passive_departure_rate: number
}

export interface DistributionItem {
  name: string
  value: number
}

export interface MonthlyByDeptItem {
  month: string
  department: string
  value: number
}

export interface MonthlyByCategoryItem {
  month: string
  category: string
  value: number
}

export interface MonthlyItem {
  month: string
  value: number
}

export interface MonthlyComparisonItem {
  month: string
  label: string
  last_year: number
  current_year: number
}

/** 各部门编制 vs 在编（部门定编表同步数据；空数组=未绑定定编表） */
export interface HeadcountDeptItem {
  name: string
  quota: number
  actual: number
}

export interface DashboardStats {
  summary: DashboardSummary
  education_distribution: DistributionItem[]
  department_distribution: DistributionItem[]
  monthly_hires_by_dept: MonthlyByDeptItem[]
  monthly_hires_by_category: MonthlyByCategoryItem[]
  monthly_departures_by_category: MonthlyByCategoryItem[]
  hires_by_dept_year: DistributionItem[]
  monthly_hires: MonthlyItem[]
  monthly_departures: MonthlyItem[]
  monthly_departure_comparison: MonthlyComparisonItem[]
  departures_by_dept: DistributionItem[]
  headcount_by_dept: HeadcountDeptItem[]
  distributions: Record<string, DistributionItem[]>
  position_departure_top: DistributionItem[]
  monthly_departure_rate: MonthlyItem[]
  contract_expiry: DistributionItem[]
}

// ─── 职称评审（v2 投票制） ───

export type TitleActivityStatus = 'draft' | 'open' | 'reviewing' | 'closed'
export type TitleApplicationStatus =
  | 'submitted' | 'voting' | 'passed' | 'failed'
  | 'final_passed' | 'final_failed' | 'invalid'

export interface TitleReviewLevel {
  id?: string
  activity_id?: string
  sequence: string
  level_name: string
  sort_order?: number
}

export interface TitleReviewActivity {
  id: string
  name: string
  status: TitleActivityStatus
  apply_deadline?: string
  review_deadline?: string
  pass_ratio: number
  feishu_app_token?: string
  apply_table_id?: string
  vote_table_id?: string
  feishu_folder_token?: string
  approval_code?: string
  created_at?: string
  levels: TitleReviewLevel[]
}

export interface TitleReviewActivityListItem extends Omit<TitleReviewActivity, 'levels'> {
  application_count?: number
  voted_judge_count?: number
  total_judge_count?: number
}

export interface TitleReviewActivityCreateInput {
  name: string
  apply_deadline?: string
  review_deadline?: string
  pass_ratio?: number
  feishu_app_token?: string
  apply_table_id?: string
  vote_table_id?: string
  approval_code?: string
  levels?: TitleReviewLevel[]
}

export interface TitleReviewActivityUpdateInput {
  name?: string
  apply_deadline?: string
  review_deadline?: string
  pass_ratio?: number
  feishu_app_token?: string
  apply_table_id?: string
  vote_table_id?: string
  levels?: TitleReviewLevel[]
}

export interface TitleReviewCommitteeMember {
  employee_id: string
  name: string
  employee_no?: string
}

export interface TitleReviewDeptCommittee {
  id: string
  department: string
  committee_members?: TitleReviewCommitteeMember[]
}

export interface TitleReviewDeptCommitteeInput {
  department: string
  committee_members: TitleReviewCommitteeMember[]
}

export interface TitleReviewApplication {
  id: string
  activity_id: string
  employee_id?: string
  employee_no: string
  name: string
  department?: string
  sequence?: string
  tech_domain?: string
  apply_level?: string
  current_level?: string
  is_exception: boolean
  exception_reason?: string
  tenure_start?: string
  tenure_end?: string
  self_evaluations?: Record<string, string>
  work_statements?: Record<string, string>
  attachments?: Record<string, { file_token: string; name: string; size: number }[]>
  profile?: Record<string, string> | null
  feishu_record_id?: string
  status: TitleApplicationStatus
  agree_votes: number
  oppose_votes: number
  abstain_votes: number
  final_result?: 'passed' | 'failed'
  final_opinion?: string
  result_notified_at?: string
  created_at?: string
}

export interface TitleReviewJudge {
  id: string
  application_id: string
  judge_employee_id: string
  judge_name: string
  judge_employee_no?: string
  judge_code: string
  judge_role?: string
  feishu_record_id?: string
  vote_result?: '同意' | '不同意' | '弃权'
  comprehensive_grade?: '合格' | '不合格'
  review_comment?: string
  voted_at?: string
}

export interface TitleReviewScore {
  id: string
  judge_id: string
  dimension_id: string
  dimension_name: string
  grade?: '合格' | '不合格'
  voted_at?: string
}

export interface TitleReviewResultRow {
  application: TitleReviewApplication
  judges: (TitleReviewJudge & { scores: TitleReviewScore[] })[]
  vote_ratio?: number
}

export interface TitleReviewReconcileStats {
  applications_created: number
  applications_removed: number
  votes_updated: number
  errors: string[]
}

export interface TitleReviewJudgeAssignItem {
  employee_id: string
  role: string
}


export interface IncidentRecord {
  id: string
  incident_type: 'work_injury' | 'labor_dispute'
  employee_name: string | null
  employee_number: string | null
  department: string | null
  occurred_date: string | null
  description: string | null
  status: string
  remark: string | null
}

// ─── 员工档案多维表格同步 ───

export interface EmployeeSyncStats {
  created?: number
  updated?: number
  deleted?: number
  total?: number
  errors?: string[]
  copy_created?: number
  copy_updated?: number
  copy_deleted?: number
  skipped?: string
  rebuilt?: number
  removed?: number
  /** 定编数表附加同步统计（绑定 headcount_table_id 后出现；error=失败原因） */
  headcount?: {
    created?: number
    updated?: number
    deleted?: number
    total?: number
    errors?: string[]
    error?: string
  }
  /** 离职台账表附加同步统计（绑定 departure_table_id 后出现） */
  departures?: {
    created?: number
    updated?: number
    deleted?: number
    total?: number
    errors?: string[]
    error?: string
  }
}

export interface EmployeeSyncColumnReport {
  mapped: string[]
  ignored: string[]
  has_employee_number: boolean
  mapped_count: number
}

export interface EmployeeSyncConfig {
  enabled: boolean
  app_token: string
  source_table_id: string
  source_table_name: string
  /** 定编数表（可选附加同步：与员工档案同一 Base，一次同步顺带拉取） */
  headcount_table_id: string
  headcount_table_name: string
  headcount_ready: boolean
  /** 离职人员管理表（可选附加同步：写入离职台账） */
  departure_table_id: string
  departure_table_name: string
  departure_ready: boolean
  is_ready: boolean
  last_sync_at: string | null
  last_stats: EmployeeSyncStats | null
  column_report?: EmployeeSyncColumnReport
}

// ─── 编制数（部门定编） ───

/** 岗位明细解析结果（「经理×1」→ {name:'经理', count:1}；无数量时 count=null） */
export interface HeadcountPosition {
  name: string
  count: number | null
}

export interface HeadcountPlanRow {
  department: string
  department_quota: number
  /** 本地实时统计的在编人数（未离职口径） */
  actual_count: number
  /** 飞书定编表手填的「现有人数」（仅对账参考，不作计算口径） */
  source_current_count: number | null
  /** 缺编 = 定编 - 在编（负数=超编） */
  vacancy: number
  position_detail: string
  positions: HeadcountPosition[]
  sort_order: number
  /** 部门名是否匹配到员工档案部门（false=建议核对名称写法） */
  matched: boolean
  feishu_synced_at: string | null
}

export interface HeadcountSummary {
  total_quota: number
  total_actual: number
  total_vacancy: number
  achievement_rate: number
  department_count: number
  unmatched_departments: string[]
}

export interface HeadcountData {
  plans: HeadcountPlanRow[]
  summary: HeadcountSummary
}

/** 员工档案页所需的同步状态精简形态（服务端注入） */
export interface EmployeeSyncBanner {
  app_token: string
  source_table_id: string
  last_sync_at: string | null
}

// ─── 新员工信息收集（飞书机器人表单卡片 → HR 审核合并档案） ───

/** 逐字段差异对比项（档案现值 vs 员工填写值） */
export interface InfoCollectionDiffEntry {
  field: string
  label: string
  current: string
  submitted: string
}

/** 信息收集任务 */
export interface EmployeeInfoCollectionItem {
  id: string
  employee_id: string
  employee_name: string
  employee_number: string | null
  department: string | null
  position: string | null
  status: 'sent' | 'submitted' | 'approved' | 'rejected'
  form_data: Record<string, string> | null
  diff: InfoCollectionDiffEntry[]
  reject_reason: string | null
  submitted_at: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string | null
}

// ─── 试用期转正评估 ───

/** 转正评估记录 */
export interface ProbationReviewItem {
  id: string
  employee_id: string
  employee_name: string
  employee_number: string | null
  department: string | null
  position: string | null
  hire_date: string | null
  probation_end: string | null
  days_left: number | null
  current_step: number
  status: 'pending_step1' | 'pending_step2' | 'pending_step3' | 'effective' | 'rejected' | 'cancelled'
  status_label: string
  direct_manager_name: string
  dept_manager_name: string | null
  leader_name: string | null
  conclusion: '通过' | '延长' | '不通过' | null
  comment: string | null
  proposed_probation_end: string | null
  dept_manager_decision: '同意' | '退回' | null
  dept_manager_comment: string | null
  leader_decision: '同意' | '退回' | null
  leader_comment: string | null
  hr_note: string | null
  direct_manager_decided_at: string | null
  dept_manager_decided_at: string | null
  leader_decided_at: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string | null
}

// ─── 员工证件资料库 ───

export type CertificateCategory =
  | 'id_card' | 'graduation' | 'professional_qualification'
  | 'special_operation' | 'health' | 'other'

export const CERTIFICATE_CATEGORY_LABELS: Record<CertificateCategory, string> = {
  id_card: '身份证',
  graduation: '学历证',
  professional_qualification: '职业资格证',
  special_operation: '特种作业操作证',
  health: '健康证',
  other: '其他',
}

export interface EmployeeCertificate {
  id: string
  employee_id: string
  category: CertificateCategory
  certificate_name: string | null
  certificate_no: string | null
  issue_date: string | null
  expiry_date: string | null
  is_permanent: boolean
  version_no: number
  is_current: boolean
  filename: string
  content_type: string
  size: number
  remark: string | null
  created_at: string | null
  /** 台账场景附带员工信息 */
  employee_name?: string
  employee_number?: string
  department?: string
  position?: string
}

export interface CertificateCategoryView {
  category: CertificateCategory
  label: string
  required: boolean
  current: EmployeeCertificate | null
  history: EmployeeCertificate[]
}

export interface EmployeeCertificatesView {
  employee: {
    id: string
    employee_number: string
    name: string
    department: string
    position: string
    status: string
    is_key_position: boolean | null
  }
  categories: CertificateCategoryView[]
  missing: { category: CertificateCategory; label: string }[]
}

export interface MissingCertificateItem {
  employee_id: string
  employee_name: string
  employee_number: string
  department: string
  is_key_position: boolean
  category: CertificateCategory
  category_label: string
}

export interface CertificateRequirement {
  id: string
  category: CertificateCategory
  applies_to: 'all' | 'key_position'
}

/** 批量导入：员工补选项（姓名/工号模糊搜索） */
export interface CertificateImportEmployeeOption {
  id: string
  name: string
  employee_number: string | null
  department: string | null
}

/** 批量导入预检行（一行 = ZIP 内一个文件） */
export interface CertificateImportRow {
  filename: string
  /** ok=自动匹配 / unmatched=未匹配 / ambiguous=重名待选 / invalid=不可导入 */
  status: 'ok' | 'unmatched' | 'ambiguous' | 'invalid'
  error: string | null
  name_hint: string | null
  employee_number_hint: string | null
  employee: CertificateImportEmployeeOption | null
  /** 重名候选（ambiguous 时） */
  candidates: CertificateImportEmployeeOption[]
  category: CertificateCategory
  /** false = 文件名里没识别出类别，默认「其他」待确认 */
  category_matched: boolean
  /** 暂存键（确认提交时原样带回） */
  storage_key: string | null
  content_type: string | null
  size: number
  /** 该员工该类别已有当前版本 → 本次导入将升版本换证 */
  replaces: { version_no: number; expiry_date: string | null; is_permanent: boolean } | null
  /** 同批同「员工×类别」多个文件 → 提交会被拒，需合并或改类别 */
  dup_in_batch: boolean
}

export interface CertificateImportPrecheck {
  rows: CertificateImportRow[]
  summary: {
    total: number
    ok: number
    unmatched: number
    ambiguous: number
    invalid: number
    replaces: number
  }
}

/** 批量导入确认提交行 */
export interface CertificateImportCommitRow {
  storage_key: string
  filename: string
  employee_id: string
  category: CertificateCategory
  certificate_name?: string | null
  certificate_no?: string | null
  issue_date?: string | null
  expiry_date?: string | null
  is_permanent?: boolean
  remark?: string | null
}

export interface CertificateImportCommitResult {
  results: {
    filename: string
    employee_name: string | null
    category_label: string
    version_no: number | null
    ok: boolean
    error: string | null
  }[]
  summary: { imported: number; failed: number }
}

export interface ProbationSafetyExamItem {
  id: string
  employee_id: string
  employee_name: string
  employee_number: string | null
  department: string | null
  exam_date: string
  passed: boolean
  score: number | null
  entered_by: string | null
  remark: string | null
}

export interface CertificateAccessLog {
  id: string
  action: string
  employee_id: string | null
  employee_name: string | null
  category: string | null
  version_no: number | null
  user_id: string | null
  created_at: string | null
}

export interface CertificateUploadInput {
  category: CertificateCategory
  certificate_name?: string
  certificate_no?: string
  issue_date?: string
  expiry_date?: string
  is_permanent?: boolean
  remark?: string
}

// ─── 台账 Excel 导入（两步预检式）───

/** 可导入的台账类型（与后端 ledger_import.LEDGER_IMPORT_SPECS 对齐） */
export type LedgerImportLedger = 'onboarding' | 'departure' | 'training' | 'incident' | 'contract'

/** 预检结果：新增/重复/错误统计及明细（明细截断 50 条） */
export interface LedgerImportPrecheck {
  total: number
  new_count: number
  duplicate_count: number
  duplicates: { row: number; key: string }[]
  error_count: number
  errors: string[]
  skipped_scope: number
  dup_key_display: string
}

/** 落库结果：created/updated/skipped 计数及行级错误 */
export interface LedgerImportResult {
  created: number
  updated: number
  skipped: number
  skipped_scope: number
  errors: string[]
}

// ─── 劳动合同管理 ───

/** 劳动合同状态（与后端 LaborContract.STATUS_* 对齐） */
export type LaborContractStatus =
  | 'active'
  | 'pending_renewal'
  | 'renewing'
  | 'superseded'
  | 'terminated'
  | 'expired_unrenewed'

export type LaborContractTermType = 'fixed_3y' | 'fixed_6y' | 'fixed' | 'open'

/** 劳动合同（一份合同一行；期限/状态标签由后端按签订次数计算下发） */
export interface LaborContract {
  id: string
  employee_number: string
  name: string
  department: string
  position?: string | null
  seq_no: number
  seq_label: string
  term_type: LaborContractTermType
  term_label: string
  term_years?: number | null
  start_date?: string | null
  end_date?: string | null
  sign_date?: string | null
  status: LaborContractStatus
  status_label: string
  remark?: string | null
  dept_decision?: 'agree' | 'disagree' | null
  dept_decision_label?: string | null
  dept_decision_by?: string | null
  dept_decision_at?: string | null
  approval_mode?: 'feishu' | 'manual' | null
  approval_mode_label?: string | null
  approval_instance_code?: string | null
  stamped_at?: string | null
  delivered_at?: string | null
  sign_confirmed_at?: string | null
  terminated_reason?: string | null
  terminated_at?: string | null
  departure_record_id?: string | null
  /** 电子归档（与合同状态正交）：合同行上的当前版扫描件快照 */
  archive_status?: ContractArchiveStatus
  archive_status_label?: string
  archive_file_name?: string | null
  archive_uploaded_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** 合同详情（含同一员工历次合同） */
export interface LaborContractDetail extends LaborContract {
  history: LaborContract[]
  /** 飞书原生审批为可选增强：配置了审批定义编码才为 true（默认站内审批） */
  renewal_approval_configured?: boolean
  /** 归档能力随数据范围变化，由后端下发：can_archive 上传/删除扫描件（仅 HR）；
   *  can_access_file 原件预览/下载（HR 与员工本人） */
  can_archive?: boolean
  can_access_file?: boolean
}

export interface LaborContractListParams {
  status?: string
  keyword?: string
  expiring_days?: number
  department?: string
  page?: number
  page_size?: number
}

export interface LaborContractCreateInput {
  employee_number: string
  start_date: string
  sign_date?: string | null
  seq_no?: number | null
  remark?: string | null
}

/** 录入预推：签订次序与期限（缺省按入职日期+期限规则推算） */
export interface ContractEntryPreview {
  employee_number: string
  seq_no: number
  seq_label: string
  term_type: string
  term_years: number | null
  end_date: string | null
  years_employed: number | null
  existing_contracts: number
}

export interface LaborContractUpdateInput {
  start_date?: string
  sign_date?: string
  position?: string
  remark?: string
}

export interface LaborContractRenewInput {
  start_date: string
  sign_date?: string | null
}

/** 签字页最小视图（免登；不含工号等可枚举信息） */
export interface ContractSignView {
  name: string
  department: string
  seq_no: number
  seq_label: string
  term_label: string
  start_date?: string | null
  end_date?: string | null
  delivered_at?: string | null
  sign_confirmed_at?: string | null
}

// ─── 劳动合同 · 电子档案库（P2）───

export type ContractArchiveStatus = 'unarchived' | 'archived'

/** 合同扫描件版本（一份合同一个合并文件；换传升版本，旧版保留可查） */
export interface ContractArchiveVersion {
  id: string
  contract_id: string
  version_no: number
  is_current: boolean
  /** 展示/下载名：工号+姓名+签订次数+起止日期（服务端生成） */
  file_name: string
  content_type: string
  size: number
  remark?: string | null
  source: 'single' | 'batch'
  uploaded_by?: string | null
  uploaded_at?: string | null
}

/** 合同扫描件调阅/下载记录 */
export interface ContractAccessLog {
  id: string
  viewer_name: string
  action: 'view' | 'download'
  action_label: string
  version_no?: number | null
  created_at?: string | null
}

/** 电子档案库台账行：合同 + 是否离职人员 + 归档能力（后端按数据范围下发） */
export interface ContractArchiveRow extends LaborContract {
  is_departed: boolean
  can_archive?: boolean
  can_access_file?: boolean
}

export interface ContractArchiveStats {
  in_service_unarchived: number
  in_service_archived: number
  departed_unarchived: number
  departed_archived: number
  /** 上传/批量挂接等归档写操作：仅 HR（后端按数据范围下发） */
  can_archive?: boolean
}

/** 未归档份数按部门（档案库部门下拉） */
export interface ContractArchiveDepartment {
  department: string
  unarchived: number
}

export interface ContractArchiveListParams {
  archive_status?: ContractArchiveStatus
  /** 在职 / 离职 / 全部（后两者仅 HR 可用，其他范围自动收敛为在职） */
  population?: 'in_service' | 'departed' | 'all'
  keyword?: string
  department?: string
  page?: number
  page_size?: number
}

/** 员工历次合同视图（员工档案「合同」页签：一人一事一档） */
export interface EmployeeContractsView {
  contracts: LaborContract[]
  /** 原件调阅权限：HR 与员工本人为 true，部门范围只有基本信息 */
  can_access_file: boolean
  /** 上传/删除扫描件：仅 HR */
  can_archive?: boolean
}

/** 批量挂接：可选的合同（多份待选 / 补选时挑签订次数） */
export interface ContractImportContractOption {
  id: string
  seq_no: number
  seq_label: string
  period: string
  status_label: string
  archive_status: ContractArchiveStatus
}

export interface ContractImportPerson {
  employee_number: string
  name: string
  department: string
  source: 'employee' | 'departure'
}

/** 批量挂接预检行 */
export interface ContractImportRow {
  filename: string
  status: 'ok' | 'ambiguous' | 'unmatched' | 'invalid'
  error?: string | null
  number_hint?: string | null
  seq_hint?: number | null
  remark?: string | null
  employee?: ContractImportPerson | null
  contract?: ContractImportContractOption | null
  /** 多份合同待选时的候选 */
  candidates?: ContractImportContractOption[]
  /** 离职人员无合同行：提交时按离职记录合同信息建档 */
  build_from_departure: boolean
  storage_key?: string | null
  content_type?: string | null
  size: number
  /** 已有扫描件：导入后升为新版本，旧版转历史 */
  replaces?: { version_no: number; file_name: string } | null
  dup_in_batch: boolean
}

export interface ContractImportPrecheck {
  rows: ContractImportRow[]
  summary: {
    total: number
    ok: number
    ambiguous: number
    unmatched: number
    invalid: number
    replaces: number
    builds: number
  }
}

/** 批量挂接补选：员工/离职人员 + 其合同清单 */
export interface ContractImportOption extends ContractImportPerson {
  contracts: ContractImportContractOption[]
  build_from_departure: boolean
}

/** 批量挂接提交行：contract_id 与 employee_number 二选一（后者用于离职人员建档后挂接） */
export interface ContractImportCommitRow {
  storage_key: string
  filename: string
  contract_id?: string | null
  employee_number?: string | null
  remark?: string | null
}

export interface ContractImportCommitResult {
  results: {
    filename: string
    employee_name?: string | null
    seq_label?: string | null
    version_no?: number | null
    ok: boolean
    error?: string | null
  }[]
  summary: { imported: number; failed: number }
}

// ─── 离职合同台账（P3）───

/** 合同终止方式：expiry 到期终止 / resign 员工辞职解除 / employer 公司解除 / retire 退休终止 /
 *  transfer 调动转签解除 / other 其他 / none 无合同记录 */
export type ContractTerminationType =
  | 'expiry'
  | 'resign'
  | 'employer'
  | 'retire'
  | 'transfer'
  | 'other'
  | 'none'

/** 离职合同台账行：人员 / 合同 / 离职信息 / 手续状态四块 */
export interface DepartureContractView {
  id: string
  // 人员信息
  name: string
  employee_number?: string | null
  department: string
  position: string
  employee_category?: string | null
  // 合同信息（按工号从合同表实时聚合；无合同行时退回离职记录自带起止日期）
  has_contract_rows: boolean
  has_contract: boolean
  contract_count: number
  /** false = 份数仅来自离职台账登记（历史离职人员不在合同表） */
  contract_count_known: boolean
  contracts: {
    id: string
    seq_no: number
    seq_label: string
    term_label: string
    start_date?: string | null
    end_date?: string | null
    status: string
    status_label: string
    terminated_reason?: string | null
    archive_status: ContractArchiveStatus
    archive_status_label: string
  }[]
  contract_periods_text: string
  contract_start_date?: string | null
  contract_end_date?: string | null
  term_type_last?: string | null
  term_label_last?: string | null
  archive_status: ContractArchiveStatus
  archive_status_label: string
  // 离职信息
  offboarding_date?: string | null
  offboarding_type: string
  offboarding_reason?: string[] | string | null
  termination_type: ContractTerminationType
  termination_type_label: string
  /** true = HR 人工更正过（否则按离职日期与离职类型自动判定） */
  termination_type_overridden: boolean
  termination_date?: string | null
  approval_ref?: string | null
  approval_refs: string[]
  // 手续状态
  separation_process_no?: string | null
  /** case 离职办结单编号 / manual 人工补录 / null 未登记 */
  process_no_source?: 'case' | 'manual' | null
  certificate_status: 'pending' | 'issued' | 'delivering' | 'signed'
  certificate_status_label: string
  contract_original_status: 'unrecovered' | 'recovered' | 'waived'
  contract_original_status_label: string
}

export interface DepartureContractListParams {
  department?: string
  date_from?: string
  date_to?: string
  termination_type?: ContractTerminationType
  keyword?: string
  page?: number
  page_size?: number
}

export interface DepartureContractFilterOptions {
  termination_types: { value: ContractTerminationType; label: string }[]
  certificate_statuses: { value: string; label: string }[]
  original_statuses: { value: NonNullable<DepartureContractView['contract_original_status']>; label: string }[]
}

/** 离职合同台账人工项（终止方式更正 / 审批依据 / 流程单号 / 原件回收状态） */
export interface DepartureContractProcedureInput {
  /** 传空串 = 清除更正，恢复自动判定 */
  termination_type?: string | null
  approval_ref?: string | null
  separation_process_no?: string | null
  contract_original_status: NonNullable<DepartureContractView['contract_original_status']>
}

// ─── 离职办理（OffboardingCase 状态机）───

export type OffboardingCaseStatus =
  | 'draft'
  | 'approving'
  | 'clearing'
  | 'cert_issuing'
  | 'delivering'
  | 'signed'
  | 'closed'
  | 'canceled'

export type ClearanceCategory = 'admin' | 'finance' | 'hr' | 'work'

export interface OffboardingClearanceItem {
  id: string
  category: ClearanceCategory
  category_label: string
  item_name: string
  status: 'pending' | 'confirmed' | 'deducted'
  status_label: string
  deduction_amount?: number | null
  supplement_amount?: number | null
  remark?: string | null
  confirmed_by?: string | null
  confirmed_at?: string | null
  /** manual HR 登记 / feishu_form 飞书实例回读 / seed 进入清退时落的默认清单 */
  source?: 'manual' | 'feishu_form' | 'seed'
}

export interface OffboardingCase {
  id: string
  case_no: string
  employee_id: string
  departure_record_id?: string | null
  employee_number: string
  name: string
  department: string
  position?: string | null
  level?: string | null
  /** 发起人姓名快照 */
  initiator_name?: string | null
  offboarding_date: string
  offboarding_type: string
  reason?: string | null
  employee_category?: string | null
  application_submitted: boolean
  status: OffboardingCaseStatus
  status_label: string
  approval_track?: 'staff' | 'director' | null
  resignation_instance_code?: string | null
  resignation_finished_at?: string | null
  clearance_instance_code?: string | null
  clearance_finished_at?: string | null
  health_check_required: boolean
  health_check_done: boolean
  health_check_date?: string | null
  health_check_file_name?: string | null
  has_health_check_file?: boolean
  /** electronic 电子单张（链接线上签收）/ paper 纸质两联（当面签收） */
  cert_template?: 'electronic' | 'paper' | null
  cert_issued_at?: string | null
  /** 开具人（HR 经办人姓名快照） */
  cert_issued_by?: string | null
  has_cert_file?: boolean
  mail_recipient?: string | null
  mail_sent_at?: string | null
  mail_status?: string | null
  sms_phone?: string | null
  sms_status?: string | null
  delivery_channel?: string | null
  paper_signed_at?: string | null
  paper_signed_by?: string | null
  account_deactivated: boolean
  closed_at?: string | null
  remark?: string | null
  created_at?: string | null
}

/** 办理详情：含清退明细与台账签字状态 */
export interface OffboardingCaseDetail extends OffboardingCase {
  clearance_items?: OffboardingClearanceItem[]
  /** 两个审批环节是否接了飞书：未接则走站内登记办结 */
  resignation_feishu?: boolean
  clearance_feishu?: boolean
  sign_state?: {
    cert_sign_status?: string | null
    cert_signed_at?: string | null
    cert_sign_name?: string | null
    has_sign_image?: boolean
    cert_issued_at?: string | null
  } | null
}

/** 看板页头统计：各状态单数 + 临期单数（审批 / 清退中且距离职日 ≤ 2 天） */
export interface OffboardingCaseStats {
  counts: Partial<Record<OffboardingCaseStatus, number>>
  overdue: number
  /** 全部有效单（不含已取消之外的历史单都算） */
  total: number
  /** 进行中：待发起 ~ 已签字 */
  active: number
}

/** 开具 / 补发送达的响应：办结单 + 交回 HR 人工转发的签署链接 */
export interface OffboardingCaseDeliveryResponse extends OffboardingCase {
  sign_url?: string | null
}

/** 离职证明签字 H5 视图（免登，token 一次性） */
export interface DepartureCertSignView {
  name: string
  department: string
  position: string
  leave_date: string
  has_pdf: boolean
  /** 联系人文案（有疑问找谁） */
  contact?: string
  certificate_html: string
}

/** 签字确认响应：签字后 token 已作废，PDF 内容随响应带回供下载 */
export interface DepartureCertSignResult {
  signed_at?: string | null
  case_status?: OffboardingCaseStatus | null
  has_pdf: boolean
  pdf_base64?: string | null
  pdf_filename?: string | null
}

// ─── 离职台账增强（筛选 / 勾选导出 / 保存视图 / 导出留痕）───

/** 台账筛选条件：键名与后端一致，保存视图 / 导出留痕里存的就是它 */
export interface DepartureLedgerFilters {
  keyword?: string
  department?: string
  position?: string
  offboarding_type?: string
  offboarding_reason?: string
  gender?: string
  education?: string
  employee_category?: string
  offboarding_date_from?: string
  offboarding_date_to?: string
  /** 办结单状态；'none' = 未发起办理 */
  approval_status?: string
  cert_issued?: boolean
  cert_signed?: boolean
}

export interface DepartureLedgerSort {
  sort_by?: 'offboarding_date' | 'name' | 'department'
  sort_order?: 'asc' | 'desc'
}

/** 台账行 = 离职台账记录 + 办理流程信息（按工号挂最近一张办结单） */
export interface DepartureLedgerRow extends DepartureRecord {
  has_sign_image?: boolean
  case_id?: string | null
  case_no?: string | null
  approval_status?: OffboardingCaseStatus | null
  approval_status_label?: string
  cert_issued?: boolean
  cert_signed?: boolean
  /** 四部门清退进度与扣补金额（没有办结单时各项为 0） */
  clearance?: Record<ClearanceCategory, ClearanceSummary>
}

export interface ClearanceSummary {
  total: number
  done: number
  deduction: number
  supplement: number
}

export interface DepartureLedgerFilterOptions {
  departments?: string[]
  positions?: string[]
  offboarding_types?: string[]
  genders?: string[]
  educations?: string[]
  employee_categories?: string[]
  offboarding_reasons?: string[]
  approval_statuses?: { value: string; label: string }[]
}

export interface DepartureExportColumn {
  key: string
  label: string
  group: string
}

export interface DepartureExportColumnCatalog {
  columns: DepartureExportColumn[]
  default_keys: string[]
}

/** 保存视图（个人维度）：常用筛选条件 + 导出字段一键调用 */
export interface DepartureSavedView {
  id: string
  name: string
  filters: DepartureLedgerFilters
  columns: string[]
  is_default: boolean
  created_at?: string | null
}

/** 导出留痕：操作人 / 时间 / 筛选条件 / 字段 / 条数 */
export interface DepartureExportLog {
  id: string
  operator_name: string
  created_at?: string | null
  /** 键已还原成中文字段名 */
  filters: Record<string, unknown>
  columns: string[]
  row_count: number
}

export interface DepartureLedgerQueryParams extends DepartureLedgerFilters, DepartureLedgerSort {
  page?: number
  page_size?: number
}
