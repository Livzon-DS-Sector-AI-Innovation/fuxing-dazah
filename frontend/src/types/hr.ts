export interface Employee {
  id: string
  employee_number: string
  name: string
  domain_account?: string
  department: string
  actual_department?: string
  team?: string
  position: string
  duty?: string
  dept_manager?: string
  report_grade?: string
  job_category?: string
  level?: string
  concurrent_departments?: string
  qualifications?: string[]
  qualification_type?: string
  gender?: string
  native_place?: string
  political_status?: string
  marital_status?: string
  household_type?: string
  status_category?: string
  birth_year?: number
  birth_month?: number
  birth_day?: number
  age?: number
  work_start_date?: string
  factory_entry_date?: string
  livo_entry_date?: string
  hire_date: string
  graduation_date?: string
  work_years?: number
  factory_tenure?: string
  company_tenure?: string
  education?: string
  classification?: string
  school?: string
  major?: string
  variety?: string
  id_card?: string
  id_card_expiry?: string
  id_card_address?: string
  current_address?: string
  contract_type?: string
  contract_start_date?: string
  contract_end_date?: string
  contract_start_2?: string
  contract_end_2?: string
  contract_start_3?: string
  contract_end_3?: string
  contract_start_4?: string
  contract_end_4?: string
  phone?: string
  email?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  bank_account?: string
  training_id?: string
  transfer_history?: string
  remarks?: string[]
  status: string
  feishu_record_id?: string
  feishu_synced_at?: string
  created_at?: string
  updated_at?: string
}

export interface EmployeeCreateInput {
  employee_number: string
  name: string
  domain_account?: string
  department: string
  team?: string
  position: string
  job_category?: string
  level?: string
  concurrent_departments?: string
  qualifications?: string[]
  qualification_type?: string
  gender?: string
  native_place?: string
  political_status?: string
  marital_status?: string
  household_type?: string
  status_category?: string
  birth_year?: number
  birth_month?: number
  birth_day?: number
  work_start_date?: string
  factory_entry_date?: string
  livo_entry_date?: string
  hire_date: string
  graduation_date?: string
  education?: string
  classification?: string
  school?: string
  major?: string
  variety?: string
  id_card?: string
  id_card_expiry?: string
  id_card_address?: string
  current_address?: string
  contract_type?: string
  contract_start_date?: string
  contract_end_date?: string
  contract_start_2?: string
  contract_end_2?: string
  contract_start_3?: string
  contract_end_3?: string
  contract_start_4?: string
  contract_end_4?: string
  phone?: string
  email?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  bank_account?: string
  training_id?: string
  transfer_history?: string
  remarks?: string[]
  status?: string
}

export interface EmployeeUpdateInput {
  employee_number?: string
  name?: string
  domain_account?: string
  department?: string
  team?: string
  position?: string
  job_category?: string
  level?: string
  concurrent_departments?: string
  qualifications?: string[]
  qualification_type?: string
  gender?: string
  native_place?: string
  political_status?: string
  marital_status?: string
  household_type?: string
  status_category?: string
  birth_year?: number
  birth_month?: number
  birth_day?: number
  work_start_date?: string
  factory_entry_date?: string
  livo_entry_date?: string
  hire_date?: string
  graduation_date?: string
  education?: string
  classification?: string
  school?: string
  major?: string
  variety?: string
  id_card?: string
  id_card_expiry?: string
  id_card_address?: string
  current_address?: string
  contract_type?: string
  contract_start_date?: string
  contract_end_date?: string
  contract_start_2?: string
  contract_end_2?: string
  contract_start_3?: string
  contract_end_3?: string
  contract_start_4?: string
  contract_end_4?: string
  phone?: string
  email?: string
  emergency_contact_name?: string
  emergency_contact_phone?: string
  emergency_contact_relation?: string
  bank_account?: string
  training_id?: string
  transfer_history?: string
  remarks?: string[]
  status?: string
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
  examiner: string
  exam_date: string
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

// ─── 招聘候选人（待后端实现）───

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
  resume_url?: string
  status?: string
  recommendation_level?: string
  feishu_record_id?: string
  feishu_sync_status?: string
  feishu_sync_error?: string
  feishu_synced_at?: string
  created_at?: string
  updated_at?: string
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
