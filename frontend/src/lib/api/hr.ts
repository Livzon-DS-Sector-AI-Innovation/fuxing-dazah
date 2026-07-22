import {
  EmployeeListResponse,
  EmployeeResponse,
  EmployeeCreateInput,
  EmployeeUpdateInput,
  DepartmentListResponse,
  DepartmentCreateInput,
  DepartmentUpdateInput,
  TeamListResponse,
  TeamCreateInput,
  TeamUpdateInput,
  OnboardingRecordListResponse,
  DepartureRecordListResponse,
} from '@/types/hr'

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.API_BASE_URL || 'http://localhost:8000'

export async function fetchEmployees(
  params?: {
    department?: string
    status?: string
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<EmployeeListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.department) searchParams.set('department', params.department)
  if (params?.status) searchParams.set('status', params.status)
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 20))

  const res = await fetch(`${API_BASE}/api/v1/hr/employees?${searchParams.toString()}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取员工列表失败')
  return res.json()
}

export async function fetchEmployeeByNumber(employeeNumber: string): Promise<EmployeeResponse> {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/by-number/${employeeNumber}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取员工详情失败')
  return res.json()
}

export async function fetchDepartments(
  params?: {
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<DepartmentListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 100))

  const res = await fetch(`${API_BASE}/api/v1/hr/departments?${searchParams.toString()}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取部门列表失败')
  return res.json()
}

export async function fetchOnboardingRecords(
  params?: {
    employee_id?: string
    department?: string
    position?: string
    is_employed?: string
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<OnboardingRecordListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.employee_id) searchParams.set('employee_id', params.employee_id)
  if (params?.department) searchParams.set('department', params.department)
  if (params?.position) searchParams.set('position', params.position)
  if (params?.is_employed) searchParams.set('is_employed', params.is_employed)
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 20))

  const res = await fetch(`${API_BASE}/api/v1/hr/onboarding-records?${searchParams.toString()}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取入职记录失败')
  return res.json()
}

export async function fetchDepartureRecords(
  params?: {
    department?: string
    offboarding_type?: string
    keyword?: string
    sort_by?: string
    sort_order?: string
    page?: number
    page_size?: number
  }
): Promise<DepartureRecordListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.department) searchParams.set('department', params.department)
  if (params?.offboarding_type) searchParams.set('offboarding_type', params.offboarding_type)
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  if (params?.sort_by) searchParams.set('sort_by', params.sort_by)
  if (params?.sort_order) searchParams.set('sort_order', params.sort_order)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 20))

  const res = await fetch(`${API_BASE}/api/v1/hr/departure-records?${searchParams.toString()}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取离职台账记录失败')
  return res.json()
}

export async function fetchOnboardingTrainingRecord(
  employeeId: string,
  employeeName: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/v1/hr/employees/${employeeId}/onboarding-training-record`,
    { cache: 'no-store', credentials: 'include' }
  )
  if (!res.ok) throw new Error('生成培训记录失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `7.3新员工入职培训记录_${employeeName}.docx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

export async function fetchPrejobTrainingPlan(
  employeeId: string,
  employeeName: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/v1/hr/employees/${employeeId}/prejob-training-plan`,
    { cache: 'no-store', credentials: 'include' }
  )
  if (!res.ok) throw new Error('生成岗前培训计划失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `7.4岗前培训计划_${employeeName}.xlsx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

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

export async function generateTrainingSignInSheet(
  data: TrainingSignInSheetData
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-sign-in-sheet`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('生成培训签到表失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const disposition = res.headers.get('content-disposition')
  const filenameMatch = disposition?.match(/filename\*=utf-8''(.+)/)
  a.download = filenameMatch
    ? decodeURIComponent(filenameMatch[1])
    : `培训签到表_${data.training_date}.docx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
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

export async function generateTrainingNotification(
  data: TrainingNotificationData
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-notification`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('生成培训通知失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `培训通知_${data.training_date}.docx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

export interface OnboardingEvaluationData {
  employee_name: string
  employee_number?: string
  gender?: string
  department_position?: string
  hire_date?: string
  training_period?: string
  regularization_date?: string
  assessment_contents?: string[]
  comprehensive_comment?: string
  is_qualified?: boolean
  assigned_position?: string
  assessment_method?: string
  dept_manager_signature?: string
  signature_date?: string
  remarks?: string
  dept_manager_agree?: boolean
  hr_manager_agree?: boolean
  qa_manager_agree?: boolean
  dept_manager?: string
  hr_manager?: string
  qa_manager?: string
  approval_date?: string
}

export async function generateOnboardingEvaluation(
  data: OnboardingEvaluationData
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/hr/onboarding-evaluation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('生成员工上岗评估表失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const safeDate = data.approval_date || 'nodate'
  a.download = `7.12员工上岗评估表_${safeDate}.xlsx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

// ─── TrainingLedger APIs ───

import {
  TrainingLedgerListResponse,
  TrainingLedgerRecord,
  TrainingLedgerCreateInput,
  TrainingLedgerUpdateInput,
} from '@/types/hr'

export async function fetchTrainingLedgers(
  params?: {
    employee_number?: string
    date_from?: string
    date_to?: string
    page?: number
    page_size?: number
  }
): Promise<TrainingLedgerListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.employee_number) searchParams.set('employee_number', params.employee_number)
  if (params?.date_from) searchParams.set('date_from', params.date_from)
  if (params?.date_to) searchParams.set('date_to', params.date_to)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 100))

  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers?${searchParams.toString()}`, {
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('获取培训台账列表失败')
  return res.json()
}

export async function createTrainingLedger(
  data: TrainingLedgerCreateInput
): Promise<{ code: number; message: string; data: TrainingLedgerRecord }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('创建培训台账记录失败')
  return res.json()
}

export async function updateTrainingLedger(
  id: string,
  data: TrainingLedgerUpdateInput
): Promise<{ code: number; message: string; data: TrainingLedgerRecord }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('更新培训台账记录失败')
  return res.json()
}

export async function deleteTrainingLedger(
  id: string
): Promise<{ code: number; message: string }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/${id}`, {
    method: 'DELETE',
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('删除培训台账记录失败')
  return res.json()
}

// ─── TrainingLedgerPage APIs ───

export interface TrainingLedgerPageRecord {
  id: string
  employee_number: string
  employee_name: string
  department?: string
  created_at: string
  updated_at: string
}

export async function fetchTrainingLedgerPages(): Promise<{
  code: number
  message: string
  data: TrainingLedgerPageRecord[]
}> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/pages`, {
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('获取培训台账页面列表失败')
  return res.json()
}

export async function createTrainingLedgerPage(
  data: { employee_number: string; employee_name: string }
): Promise<{ code: number; message: string; data: TrainingLedgerPageRecord }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/pages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('创建培训台账页面失败')
  return res.json()
}

export async function exportTrainingLedger(employeeNumber: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/v1/hr/training-ledgers/export?employee_number=${encodeURIComponent(employeeNumber)}`,
    { cache: 'no-store', credentials: 'include' }
  )
  if (!res.ok) throw new Error('导出培训台账失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const disposition = res.headers.get('content-disposition')
  const filenameMatch = disposition?.match(/filename\*=utf-8''(.+)/)
  a.download = filenameMatch ? decodeURIComponent(filenameMatch[1]) : '培训台账.xlsx'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

// ─── AnnualTrainingPlan APIs ───

import {
  AnnualTrainingPlanListResponse,
  AnnualTrainingPlan,
  AnnualTrainingPlanItem,
} from '@/types/hr'

export async function fetchAnnualTrainingPlans(
  params?: {
    year?: number
    department?: string
    page?: number
    page_size?: number
  }
): Promise<AnnualTrainingPlanListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.year) searchParams.set('year', String(params.year))
  if (params?.department) searchParams.set('department', params.department)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 100))

  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans?${searchParams.toString()}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取年度培训计划列表失败')
  return res.json()
}

// ─── New Factory APIs ───

export async function fetchAnnualTrainingPlanById(id: string): Promise<{ code: number; message: string; data: AnnualTrainingPlan }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${id}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取年度培训计划详情失败')
  return res.json()
}

export async function fetchPlanItems(id: string): Promise<{ code: number; message: string; data: AnnualTrainingPlanItem[] }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${id}/items`, {
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('获取年度计划明细失败')
  return res.json()
}

// ─── 招聘候选人（待后端实现）───

export async function fetchCandidates(params: Record<string, any> = {}): Promise<{ data: any[]; meta?: { total: number } }> {
  // TODO: backend candidate API not yet implemented
  return { data: [], meta: { total: 0 } }
}

// ─── Position APIs ───

export interface PositionOption {
  id: string
  department: string
  name: string
}

export async function fetchPositions(department?: string): Promise<PositionOption[]> {
  const sp = new URLSearchParams()
  if (department) sp.set('department', department)
  const res = await fetch(`${API_BASE}/api/v1/hr/positions?${sp.toString()}`, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) throw new Error('获取职位列表失败')
  const d = await res.json()
  return d.data || []
}

// ─── SOP Catalog APIs ───

export async function fetchCandidateById(id: string): Promise<{ code: number; message: string; data: any }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/candidates/${id}`, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) throw new Error('获取候选人失败')
  return res.json()
}

// ─── 资料打印 APIs ───

async function downloadDocumentBlob(url: string, fallbackName: string): Promise<void> {
  const res = await fetch(url, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) {
    let msg = '下载失败'
    try {
      const d = await res.json()
      msg = d.message || d.detail || msg
    } catch { /* 非 JSON 响应，用默认提示 */ }
    if (res.status === 401) msg = '请先登录'
    if (res.status === 403) msg = '没有下载权限，请联系管理员配置'
    throw new Error(msg)
  }
  const blob = await res.blob()
  const objectUrl = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  const disposition = res.headers.get('content-disposition')
  const filenameMatch = disposition?.match(/filename\*=utf-8''(.+)/)
  a.download = filenameMatch ? decodeURIComponent(filenameMatch[1]) : fallbackName
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(objectUrl)
}

export async function downloadRoster(department?: string): Promise<void> {
  const sp = new URLSearchParams()
  if (department) sp.set('department', department)
  await downloadDocumentBlob(
    `${API_BASE}/api/v1/hr/roster?${sp.toString()}`,
    `花名册_${department || '全部'}.docx`
  )
}

export async function downloadTrainingRegistration(department?: string): Promise<void> {
  const sp = new URLSearchParams()
  if (department) sp.set('department', department)
  await downloadDocumentBlob(
    `${API_BASE}/api/v1/hr/training-registration?${sp.toString()}`,
    `个人培训登记表_${department || '全部'}.docx`
  )
}

// ─── Admin Training Ledger APIs ───

export async function fetchTrainingLedgersAdmin(params?: {
  department?: string
  training_subject?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}): Promise<{ code: number; message: string; data: any[]; meta: { page: number; page_size: number; total: number } }> {
  const sp = new URLSearchParams()
  if (params?.department) sp.set('department', params.department)
  if (params?.training_subject) sp.set('training_subject', params.training_subject)
  if (params?.date_from) sp.set('date_from', params.date_from)
  if (params?.date_to) sp.set('date_to', params.date_to)
  sp.set('page', String(params?.page || 1))
  sp.set('page_size', String(params?.page_size || 20))
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/admin?${sp.toString()}`, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) throw new Error('获取管理员台账列表失败')
  return res.json()
}

export async function batchUpdateScores(data: { records: { id: string; assessment_result: string }[] }): Promise<{ code: number; message: string; data: { updated: number } }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/batch-scores`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('批量更新成绩失败')
  return res.json()
}

export async function fetchTrainingLedgerStats(params?: {
  department?: string
  training_subject?: string
  date_from?: string
  date_to?: string
}): Promise<{ code: number; message: string; data: { total_count: number; assessed_count: number; qualified_count: number; unqualified_count: number; pass_rate: string; avg_score: number | null } }> {
  const sp = new URLSearchParams()
  if (params?.department) sp.set('department', params.department)
  if (params?.training_subject) sp.set('training_subject', params.training_subject)
  if (params?.date_from) sp.set('date_from', params.date_from)
  if (params?.date_to) sp.set('date_to', params.date_to)
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/admin/stats?${sp.toString()}`, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) throw new Error('获取培训统计失败')
  return res.json()
}

export async function fetchLedgerDepartments(): Promise<{ code: number; message: string; data: string[] }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/admin/departments`, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) throw new Error('获取台账部门列表失败')
  return res.json()
}

export async function fetchLedgerSubjects(department?: string): Promise<{ code: number; message: string; data: string[] }> {
  const sp = new URLSearchParams()
  if (department) sp.set('department', department)
  const res = await fetch(`${API_BASE}/api/v1/hr/training-ledgers/admin/subjects?${sp.toString()}`, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) throw new Error('获取培训内容列表失败')
  return res.json()
}

export async function exportQaRecord(params: {
  training_content: string
  training_purpose?: string
  training_date: string
  training_method: string
  training_department: string
  questions: { file_no: string; question: string; answer: string; score: number }[]
  trainee_names: string[]
}): Promise<void> {
  const fd = new FormData()
  fd.append('training_content', params.training_content)
  fd.append('training_purpose', params.training_purpose || '')
  fd.append('training_date', params.training_date)
  fd.append('training_method', params.training_method)
  fd.append('training_department', params.training_department)
  fd.append('questions_json', JSON.stringify(params.questions))
  fd.append('trainee_names_json', JSON.stringify(params.trainee_names))
  const res = await fetch(`${API_BASE}/api/v1/hr/training-notification/export-qa-record`, {
    method: 'POST',
    body: fd,
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('导出问答记录表失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const disposition = res.headers.get('content-disposition')
  const filenameMatch = disposition?.match(/filename\*=utf-8''(.+)/)
  a.download = filenameMatch ? decodeURIComponent(filenameMatch[1]) : `问答实操记录表_${params.training_date}.docx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

export async function exportTrainingEvaluationReport(params: {
  department: string
  training_subject: string
  training_date?: string
  training_method?: string
  trainer_name?: string
  assessment_method?: string
}): Promise<void> {
  const fd = new FormData()
  fd.append('department', params.department)
  fd.append('training_subject', params.training_subject)
  if (params.training_date) fd.append('training_date', params.training_date)
  if (params.training_method) fd.append('training_method', params.training_method)
  if (params.trainer_name) fd.append('trainer_name', params.trainer_name)
  if (params.assessment_method) fd.append('assessment_method', params.assessment_method)
  const res = await fetch(`${API_BASE}/api/v1/hr/training-evaluations/export-admin`, {
    method: 'POST',
    body: fd,
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('导出评估表失败')
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const disposition = res.headers.get('content-disposition')
  const filenameMatch = disposition?.match(/filename\*=utf-8''(.+)/)
  a.download = filenameMatch ? decodeURIComponent(filenameMatch[1]) : `培训效果评估表_${params.department}.docx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

// ─── 问答/实操考核 APIs ───

import type { QaAssessment, QaAssessmentScore } from '@/types/hr'

export async function fetchQaAssessments(params?: {
  department?: string; keyword?: string; page?: number; page_size?: number
}): Promise<{ data: QaAssessment[]; meta?: { total: number } }> {
  const sp = new URLSearchParams()
  if (params?.department) sp.set('department', params.department)
  if (params?.keyword) sp.set('keyword', params.keyword)
  sp.set('page', String(params?.page || 1))
  sp.set('page_size', String(params?.page_size || 20))
  const res = await fetch(`${API_BASE}/api/v1/hr/qa-assessments?${sp.toString()}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取考核场次列表失败')
  return res.json()
}

export async function fetchQaAssessmentDetail(id: string): Promise<{
  data: { assessment: QaAssessment; scores: QaAssessmentScore[]; statistics: Record<string, unknown> }
}> {
  const res = await fetch(`${API_BASE}/api/v1/hr/qa-assessments/${id}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('获取考核详情失败')
  return res.json()
}

export async function downloadQaAssessmentRecord(id: string): Promise<void> {
  await downloadDocumentBlob(
    `${API_BASE}/api/v1/hr/qa-assessments/${id}/export-record`,
    '问答实操记录表.docx'
  )
}

export async function downloadQaAssessmentEvaluation(id: string, expectedCount?: number): Promise<void> {
  const sp = new URLSearchParams()
  if (expectedCount) sp.set('expected_count', String(expectedCount))
  await downloadDocumentBlob(
    `${API_BASE}/api/v1/hr/qa-assessments/${id}/export-evaluation?${sp.toString()}`,
    '培训效果评估表.docx'
  )
}

export async function fetchQuestionBank(params?: {
  file_no?: string; keyword?: string; department?: string; page?: number; page_size?: number
}): Promise<{ data: import('@/types/hr').QuestionBankItem[]; meta?: { total: number } }> {
  const sp = new URLSearchParams()
  if (params?.file_no) sp.set('file_no', params.file_no)
  if (params?.keyword) sp.set('keyword', params.keyword)
  if (params?.department) sp.set('department', params.department)
  sp.set('page', String(params?.page || 1))
  sp.set('page_size', String(params?.page_size || 50))
  const res = await fetch(`${API_BASE}/api/v1/hr/question-bank?${sp.toString()}`, {
    cache: 'no-store',
    credentials: 'include',
  })
  if (!res.ok) throw new Error('题库检索失败')
  return res.json()
}

// ─── 笔试试卷 APIs ───

export async function fetchExamPapers(params?: {
  department?: string; keyword?: string; page?: number; page_size?: number
}): Promise<{ data: any[]; meta?: { total: number } }> {
  const sp = new URLSearchParams()
  if (params?.department) sp.set('department', params.department)
  if (params?.keyword) sp.set('keyword', params.keyword)
  sp.set('page', String(params?.page || 1))
  sp.set('page_size', String(params?.page_size || 20))
  const res = await fetch(`${API_BASE}/api/v1/hr/exam-papers?${sp.toString()}`, {
    cache: 'no-store', credentials: 'include',
  })
  if (!res.ok) throw new Error('获取考卷列表失败')
  return res.json()
}

export async function downloadExamPaper(id: string): Promise<void> {
  await downloadDocumentBlob(`${API_BASE}/api/v1/hr/exam-papers/${id}/download`, '考卷.docx')
}

export async function saveExamPaper(payload: Record<string, unknown>): Promise<{ code: number; message: string; data: any }> {
  const res = await fetch(`${API_BASE}/api/v1/hr/exam-papers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || err.detail || '保存考卷失败')
  }
  return res.json()
}
