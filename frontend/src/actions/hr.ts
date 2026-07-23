'use server'

import { revalidatePath } from 'next/cache'
import { getAuthHeaders } from '@/lib/auth'
import {
  EmployeeCreateInput,
  EmployeeUpdateInput,
  EmployeeListResponse,
  DepartmentCreateInput,
  DepartmentUpdateInput,
  DepartmentListResponse,
  TeamCreateInput,
  TeamUpdateInput,
  TeamListResponse,
  AnnualTrainingPlanCreateInput,
  AnnualTrainingPlanUpdateInput,
  AnnualTrainingPlanListResponse,
  AnnualTrainingPlanItemBatchUpdateInput,
} from '@/types/hr'

const API_BASE = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export async function fetchEmployeesAction(
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
    headers: await getAuthHeaders(),
  })
  if (!res.ok) throw new Error('获取员工列表失败')
  return res.json()
}

export async function createEmployee(data: EmployeeCreateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees`, {
    method: 'POST',
    headers: await getAuthHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '创建员工失败')
  }
  revalidatePath('/hr/profile')
  return res.json()
}

export async function fetchEmployeeByNumberAction(employeeNumber: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/by-number/${encodeURIComponent(employeeNumber)}`, {
    cache: 'no-store',
    headers: await getAuthHeaders(),
  })
  if (!res.ok) throw new Error('获取员工详情失败')
  return res.json()
}

export async function updateEmployee(id: string, data: EmployeeUpdateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/${id}`, {
    method: 'PUT',
    headers: await getAuthHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '更新员工失败')
  }
  revalidatePath('/hr/profile')
  return res.json()
}

export async function deleteEmployee(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/${id}`, {
    method: 'DELETE',
    headers: await getAuthHeaders(),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除员工失败')
  }
  revalidatePath('/hr/profile')
  return res.json()
}

// ─── Department Actions ───

export async function fetchDepartmentsAction(
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
    headers: await getAuthHeaders(),
  })
  if (!res.ok) throw new Error('获取部门列表失败')
  return res.json()
}

export async function createDepartment(data: DepartmentCreateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/departments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '创建部门失败')
  }
  revalidatePath('/hr/departments')
  return res.json()
}

export async function updateDepartment(id: string, data: DepartmentUpdateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/departments/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '更新部门失败')
  }
  revalidatePath('/hr/departments')
  return res.json()
}

export async function deleteDepartment(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/departments/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除部门失败')
  }
  revalidatePath('/hr/departments')
  return res.json()
}

export async function deleteDepartureRecordAction(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/departure-records/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除离职记录失败')
  }
  revalidatePath('/hr/departure')
  return res.json()
}

// ─── Team Actions ───

export async function fetchTeamsAction(
  params?: {
    department_id?: string
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<TeamListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.department_id) searchParams.set('department_id', params.department_id)
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 100))

  const res = await fetch(`${API_BASE}/api/v1/hr/teams?${searchParams.toString()}`, {
    cache: 'no-store',
    headers: await getAuthHeaders(),
  })
  if (!res.ok) throw new Error('获取班组列表失败')
  return res.json()
}

export async function createTeam(data: TeamCreateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/teams`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '创建班组失败')
  }
  revalidatePath('/hr/departments')
  return res.json()
}

export async function updateTeam(id: string, data: TeamUpdateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/teams/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '更新班组失败')
  }
  revalidatePath('/hr/departments')
  return res.json()
}

export async function deleteTeam(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/teams/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除班组失败')
  }
  revalidatePath('/hr/departments')
  return res.json()
}

// ─── AnnualTrainingPlan Actions ───

export async function createAnnualTrainingPlan(data: AnnualTrainingPlanCreateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '创建年度培训计划失败')
  }
  revalidatePath('/hr/training/annual-plan')
  return res.json()
}

export async function deleteAnnualTrainingPlan(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除年度培训计划失败')
  }
  revalidatePath('/hr/training/annual-plan')
  return res.json()
}

export async function batchUpdatePlanItems(id: string, data: AnnualTrainingPlanItemBatchUpdateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${id}/items/batch`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '更新年度计划明细失败')
  }
  revalidatePath('/hr/training/annual-plan')
  return res.json()
}

// ─── 招聘候选人 ───

export async function parseResumePreviewAction(formData: FormData): Promise<{ data: any }> {
  const headers = await getAuthHeaders(); delete headers['Content-Type']
  const res = await fetch(`${API_BASE}/api/v1/hr/candidates/parse-resume`, {
    method: 'POST', body: formData, headers,
  })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message || '简历解析失败') }
  return res.json()
}

export async function createCandidateAction(formData: FormData): Promise<{ data: any }> {
  // Construct JSON from FormData fields (as originally sent by CreateCandidateModal)
  const data: Record<string, unknown> = {}
  const keys = ['name', 'phone', 'email', 'position', 'department', 'gender', 'school', 'education', 'major', 'status', 'recommendation_level', 'match_report', 'resume_file_path']
  for (const k of keys) {
    const v = formData.get(k)
    if (v) data[k] = v
  }
  const res = await fetch(`${API_BASE}/api/v1/hr/candidates`, {
    method: 'POST', headers: await getAuthHeaders(), body: JSON.stringify(data),
  })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message || '创建失败') }
  return res.json()
}

export async function updateCandidateAction(id: string, data: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/hr/candidates/${id}`, {
    method: 'PUT', headers: await getAuthHeaders(), body: JSON.stringify(data),
  })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message || '更新失败') }
}

export async function deleteCandidateAction(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/hr/candidates/${id}`, {
    method: 'DELETE', headers: await getAuthHeaders(),
  })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message || '删除失败') }
}

export async function updateCandidateRecommendationLevelAction(id: string, level: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/hr/candidates/${id}`, {
    method: 'PUT', headers: await getAuthHeaders(), body: JSON.stringify({ recommendation_level: level }),
  })
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message || '更新失败') }
}

// ─── 问答/实操考核 Actions ───

export async function createQaAssessment(data: import('@/types/hr').QaAssessmentCreateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/qa-assessments`, {
    method: 'POST',
    headers: await getAuthHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || err.detail || '创建考核场次失败')
  }
  revalidatePath('/hr/training/qa-assessment')
  return res.json()
}

export async function saveQaAssessmentScores(id: string, data: import('@/types/hr').QaScoreSaveInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/qa-assessments/${id}/scores`, {
    method: 'PUT',
    headers: await getAuthHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || err.detail || '保存成绩失败')
  }
  return res.json()
}

export async function deleteQaAssessment(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/qa-assessments/${id}`, {
    method: 'DELETE',
    headers: await getAuthHeaders(),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || err.detail || '删除考核场次失败')
  }
  revalidatePath('/hr/training/qa-assessment')
  return res.json()
}

export async function addQuestionBankItems(items: {
  file_no?: string; subject?: string; question: string; answer?: string; score?: number; department?: string
}[], source = '手工录入') {
  const res = await fetch(`${API_BASE}/api/v1/hr/question-bank`, {
    method: 'POST',
    headers: await getAuthHeaders(),
    body: JSON.stringify({ items, source }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || err.detail || '题目入库失败')
  }
  return res.json()
}

export async function deleteQuestionBankItem(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/question-bank/${id}`, {
    method: 'DELETE',
    headers: await getAuthHeaders(),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || err.detail || '删除题目失败')
  }
  return res.json()
}
