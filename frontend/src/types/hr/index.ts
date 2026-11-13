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
  created_at?: string
  updated_at?: string
  /** 从出生日期动态计算的年龄（优先于飞书静态值） */
  computed_age?: number
  /** 从入职日期动态计算的司龄，格式如"3年5个月" */
  computed_tenure?: string
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

export interface Team {
  id: string
  name: string
  code?: string
  description?: string
  department_id: string
  department?: Department
  created_at?: string
  updated_at?: string
}

export interface TeamCreateInput {
  name: string
  code?: string
  description?: string
  department_id: string
}

export interface TeamUpdateInput {
  name?: string
  code?: string
  description?: string
  department_id?: string
}

export interface TeamListResponse {
  code: number
  message: string
  data: Team[]
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
  department: string
  team?: string
  position: string
  job_category?: string
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
  classification?: string
  id_card?: string
  native_place?: string
  household_type?: string
  marital_status?: string
  political_status?: string
  phone?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  bank_account?: string
  contract_type?: string
  transfer_history?: string
  offboarding_type: string
  offboarding_reason?: string[]
  offboarding_reason_2?: string[]
  offboarding_remarks?: string[]
  remarks?: string[]
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

export interface DashboardSummary {
  total_employees: number
  new_hires_this_month: number
  departures_this_month: number
  today_hires: number
  today_departures: number
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
  is_ready: boolean
  last_sync_at: string | null
  last_stats: EmployeeSyncStats | null
  column_report?: EmployeeSyncColumnReport
}

/** 员工档案页所需的同步状态精简形态（服务端注入） */
export interface EmployeeSyncBanner {
  app_token: string
  source_table_id: string
  last_sync_at: string | null
}
