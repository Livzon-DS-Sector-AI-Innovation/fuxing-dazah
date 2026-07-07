'use server'

import { revalidatePath } from 'next/cache'
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
  OffboardingRecordCreateInput,
  OffboardingRecordUpdateInput,
  OffboardingRecordListResponse,
} from '@/types/hr'

const API_BASE = process.env.API_BASE_URL || 'http://127.0.0.1:8000'

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
  })
  if (!res.ok) throw new Error('获取员工列表失败')
  return res.json()
}

export async function createEmployee(data: EmployeeCreateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '创建员工失败')
  }
  revalidatePath('/hr/profile')
  return res.json()
}

export async function updateEmployee(id: string, data: EmployeeUpdateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
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
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除员工失败')
  }
  revalidatePath('/hr/profile')
  return res.json()
}

export async function uploadEmployeesAction(formData: FormData) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/upload`, {
    method: 'POST',
    // 不设置 Content-Type，让 fetch 自动生成带 boundary 的 multipart/form-data
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '上传员工名单失败')
  }
  return res.json()
}

// ─── Feishu Sync Actions ───

export async function syncFromFeishuAction() {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/sync-from-feishu`, {
    method: 'POST',
    cache: 'no-store',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '从飞书同步失败')
  }
  revalidatePath('/hr/profile')
  return res.json()
}

export async function syncToFeishuAction(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/employees/${id}/sync-to-feishu`, {
    method: 'POST',
    cache: 'no-store',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '同步到飞书失败')
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

// ─── OffboardingRecord Actions ───

export async function fetchOffboardingRecordsAction(
  params?: {
    employee_id?: string
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<OffboardingRecordListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.employee_id) searchParams.set('employee_id', params.employee_id)
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 20))

  const res = await fetch(`${API_BASE}/api/v1/hr/offboarding-records?${searchParams.toString()}`, {
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取离职记录失败')
  return res.json()
}

export async function createOffboardingRecord(data: OffboardingRecordCreateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/offboarding-records`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '创建离职记录失败')
  }
  revalidatePath('/hr/offboarding')
  revalidatePath('/hr/profile')
  return res.json()
}

export async function updateOffboardingRecord(id: string, data: OffboardingRecordUpdateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/offboarding-records/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '更新离职记录失败')
  }
  revalidatePath('/hr/offboarding')
  return res.json()
}

export async function deleteOffboardingRecord(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/offboarding-records/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除离职记录失败')
  }
  revalidatePath('/hr/offboarding')
  return res.json()
}

// ─── AnnualTrainingPlan Actions ───

import {
  AnnualTrainingPlanCreateInput,
  AnnualTrainingPlanListResponse,
  AnnualTrainingPlanUpdateInput,
  AnnualTrainingPlanItemBatchUpdateInput,
} from '@/types/hr'

export async function fetchAnnualTrainingPlansAction(
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
  })
  if (!res.ok) throw new Error('获取年度培训计划列表失败')
  return res.json()
}

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

export async function updateAnnualTrainingPlan(id: string, data: AnnualTrainingPlanUpdateInput) {
  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '更新年度培训计划失败')
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

export async function uploadAnnualPlanAction(formData: FormData) {
  const res = await fetch(`${API_BASE}/api/v1/hr/annual-training-plans/upload`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '上传年度培训计划失败')
  }
  return res.json()
}

// ─── 内训师 Actions ───

export async function fetchTrainersAction(params?: {
  keyword?: string
  department?: string
  page?: number
  page_size?: number
}) {
  const searchParams = new URLSearchParams()
  if (params?.keyword) searchParams.set('keyword', params.keyword)
  if (params?.department) searchParams.set('department', params.department)
  searchParams.set('page', String(params?.page || 1))
  searchParams.set('page_size', String(params?.page_size || 50))

  const res = await fetch(`${API_BASE}/api/v1/hr/trainers?${searchParams.toString()}`, {
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取内训师列表失败')
  return res.json()
}

export async function uploadTrainersAction(formData: FormData) {
  const res = await fetch(`${API_BASE}/api/v1/hr/trainers/upload`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '上传内训师失败')
  }
  return res.json()
}

export async function deleteTrainerAction(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/trainers/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除内训师失败')
  }
  return res.json()
}

export async function clearTrainersAction() {
  const res = await fetch(`${API_BASE}/api/v1/hr/trainers`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '清空内训师台账失败')
  }
  return res.json()
}

// ─── 离职台账 Actions ───

export async function deleteDepartureRecordAction(id: string) {
  const res = await fetch(`${API_BASE}/api/v1/hr/departure-records/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '删除离职记录失败')
  }
  return res.json()
}

// ─── 招聘候选人（待后端实现）───

export async function createCandidateAction(_formData: FormData): Promise<{ data: any }> {
  throw new Error('招聘功能暂未实现')
}

export async function deleteCandidateAction(_id: string): Promise<void> {
  throw new Error('招聘功能暂未实现')
}

export async function syncCandidatesFromFeishuAction(): Promise<{ data: any; message: string }> {
  throw new Error('招聘功能暂未实现')
}

export async function syncCandidateToFeishuAction(_id: string): Promise<void> {
  throw new Error('招聘功能暂未实现')
}

export async function updateCandidateAction(_id: string, _data: Record<string, unknown>): Promise<void> {
  throw new Error('招聘功能暂未实现')
}

export async function updateCandidateRecommendationLevelAction(_id: string, _level: string): Promise<void> {
  throw new Error('招聘功能暂未实现')
}

export async function parseResumePreviewAction(_formData: FormData): Promise<{ data: any }> {
  throw new Error('招聘功能暂未实现')
}
