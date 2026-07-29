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
  PositionOption,
} from '@/types/hr'
import { fetchHrApi } from './_helpers'
import { buildQueryString } from './_utils'

// ─── 员工 ───

export async function fetchEmployeesAction(
  params?: {
    department?: string
    status?: string
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<EmployeeListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi<EmployeeListResponse>(`/hr/employees${qs}`, { errorMessage: '获取员工列表失败' })
}

export async function createEmployee(data: EmployeeCreateInput) {
  const res = await fetchHrApi('/hr/employees', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建员工失败',
  })
  revalidatePath('/hr/profile')
  return res
}

export async function fetchEmployeeByNumberAction(employeeNumber: string) {
  return fetchHrApi(`/hr/employees/by-number/${encodeURIComponent(employeeNumber)}`, { errorMessage: '获取员工详情失败' })
}

export async function updateEmployee(id: string, data: EmployeeUpdateInput) {
  const res = await fetchHrApi(`/hr/employees/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新员工失败',
  })
  revalidatePath('/hr/profile')
  return res
}

export async function deleteEmployee(id: string) {
  const res = await fetchHrApi(`/hr/employees/${id}`, {
    method: 'DELETE',
    errorMessage: '删除员工失败',
  })
  revalidatePath('/hr/profile')
  return res
}

/** 批量导入员工（Excel 上传） */
export async function uploadEmployees(formData: FormData): Promise<{ code: number; message: string; data: { created: number; updated: number; errors?: string[] } }> {
  return fetchHrApi('/hr/employees/upload', {
    method: 'POST',
    body: formData,
    errorMessage: '上传失败',
  })
}

/** 试用期到期预警列表 */
export async function fetchProbationExpiring(params?: { days?: number; department?: string }): Promise<{ data: any[] }> {
  const qs = buildQueryString({ days: params?.days ?? 0, department: params?.department })
  return fetchHrApi(`/hr/employees/probation-expiring${qs}`, { errorMessage: '加载失败' })
}

/** 批量转正 */
export async function batchRegularizeEmployees(ids: string[]): Promise<{ code: number; message: string; data?: { count?: number } }> {
  return fetchHrApi('/hr/employees/batch-regularize', {
    method: 'PUT',
    body: JSON.stringify(ids),
    errorMessage: '操作失败',
  })
}

/** 试用期延期记录 */
export async function fetchProbationExtensions(id: string): Promise<{ data: unknown[] }> {
  return fetchHrApi(`/hr/employees/${id}/probation-extensions`, { errorMessage: '获取延期记录失败' })
}

/** 待培训员工（岗前培训候选人） */
export async function fetchTrainingCandidates(keyword?: string): Promise<{ data: unknown[] }> {
  const qs = buildQueryString({ keyword })
  return fetchHrApi(`/hr/employees/training-candidates${qs}`, { errorMessage: '加载失败' })
}

// ─── 员工异动 ───

export async function fetchTransfers(params: { employee_id: string; page_size?: number }): Promise<{ data: unknown[] }> {
  const qs = buildQueryString(params)
  return fetchHrApi(`/hr/transfers${qs}`, { errorMessage: '获取异动记录失败' })
}

export async function createTransfer(data: {
  employee_id: string
  transfer_type: string
  from_department?: string | null
  to_department?: string | null
  from_position?: string | null
  to_position?: string | null
  effective_date: string
  reason?: string | null
}) {
  return fetchHrApi('/hr/transfers', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建失败',
  })
}

// ─── 部门 ───

export async function fetchDepartmentsAction(
  params?: {
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<DepartmentListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 100 })
  return fetchHrApi<DepartmentListResponse>(`/hr/departments${qs}`, { errorMessage: '获取部门列表失败' })
}

export async function createDepartment(data: DepartmentCreateInput) {
  const res = await fetchHrApi('/hr/departments', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建部门失败',
  })
  revalidatePath('/hr/departments')
  return res
}

export async function updateDepartment(id: string, data: DepartmentUpdateInput) {
  const res = await fetchHrApi(`/hr/departments/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新部门失败',
  })
  revalidatePath('/hr/departments')
  return res
}

export async function deleteDepartment(id: string) {
  const res = await fetchHrApi(`/hr/departments/${id}`, {
    method: 'DELETE',
    errorMessage: '删除部门失败',
  })
  revalidatePath('/hr/departments')
  return res
}

// ─── 班组 ───

export async function fetchTeamsAction(
  params?: {
    department_id?: string
    keyword?: string
    page?: number
    page_size?: number
  }
): Promise<TeamListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 100 })
  return fetchHrApi<TeamListResponse>(`/hr/teams${qs}`, { errorMessage: '获取班组列表失败' })
}

export async function createTeam(data: TeamCreateInput) {
  const res = await fetchHrApi('/hr/teams', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建班组失败',
  })
  revalidatePath('/hr/departments')
  return res
}

export async function updateTeam(id: string, data: TeamUpdateInput) {
  const res = await fetchHrApi(`/hr/teams/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
    errorMessage: '更新班组失败',
  })
  revalidatePath('/hr/departments')
  return res
}

export async function deleteTeam(id: string) {
  const res = await fetchHrApi(`/hr/teams/${id}`, {
    method: 'DELETE',
    errorMessage: '删除班组失败',
  })
  revalidatePath('/hr/departments')
  return res
}

// ─── 职位 ───

export async function fetchPositions(department?: string): Promise<PositionOption[]> {
  const qs = buildQueryString({ department })
  const d = await fetchHrApi<{ data: PositionOption[] }>(`/hr/positions${qs}`, { errorMessage: '获取职位列表失败' })
  return d.data || []
}

export async function createPosition(data: { department: string; name: string }) {
  return fetchHrApi('/hr/positions', {
    method: 'POST',
    body: JSON.stringify(data),
    errorMessage: '创建失败',
  })
}

export async function deletePositionByName(name: string, department?: string) {
  return fetchHrApi(`/hr/positions/by-name/${encodeURIComponent(name)}?department=${encodeURIComponent(department ?? '')}`, {
    method: 'DELETE',
    errorMessage: '删除失败',
  })
}
