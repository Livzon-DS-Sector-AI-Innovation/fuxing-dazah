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

export interface Department {
  id: string
  name: string
  code: string
  description?: string
  /** 部门负责人（转正审批第二级） */
  department_manager_name?: string | null
  /** 分管领导（转正审批第三级） */
  supervising_leader_name?: string | null
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
  classification: string | null
  personnel: SopTrainingPersonnel[]
  personnel_count: number
  transferred_by: string | null
  transferred_at: string | null
  created_at: string
  updated_at: string
}

export interface SopClassificationOption {
  tag_name: string
  count: number
}

export interface SopPersonnelOption {
  employee_number: string
  name: string
  position: string
  status: string
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
export type LedgerImportLedger = 'onboarding' | 'departure' | 'training' | 'incident'

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
