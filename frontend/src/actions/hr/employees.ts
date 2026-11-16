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
  EmployeeFilterOptions,
} from '@/types/hr'
import { fetchHrApi, fetchHrDownload } from './_helpers'
import { buildQueryString } from './_utils'

// ─── 员工 ───

export async function fetchEmployeesAction(
  params?: {
    department?: string
    status?: string
    keyword?: string
    page?: number
    page_size?: number
    include_uncategorized?: boolean
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
): Promise<EmployeeListResponse> {
  const qs = buildQueryString({ ...params, page: params?.page || 1, page_size: params?.page_size || 20 })
  return fetchHrApi<EmployeeListResponse>(`/hr/employees${qs}`, { errorMessage: '获取员工列表失败' })
}

/** 员工筛选下拉选项：各可枚举字段的现有取值聚合 */
export async function fetchEmployeeFilterOptionsAction(): Promise<EmployeeFilterOptions> {
  const res = await fetchHrApi<{ code: number; message: string; data: EmployeeFilterOptions }>(
    '/hr/employees/filter-options',
    { errorMessage: '获取筛选选项失败' },
  )
  return res.data || {}
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

/** 导出员工档案（Excel），列头与导入模板一致 */
export async function exportEmployees(): Promise<{ base64: string; filename: string }> {
  const { base64, filename } = await fetchHrDownload('/hr/employees/export', {
    errorMessage: '导出员工档案失败',
  })
  return { base64, filename: filename || `员工档案_${new Date().toISOString().slice(0, 10)}.xlsx` }
}

/** 试用期延期记录 */
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

export async function createPosition(data: { department: string; name: string; headcount?: number | null }) {
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


export async function updatePositionHeadcount(department: string, name: string, headcount: number | null): Promise<{ message: string }> {
  return fetchHrApi(`/hr/positions/by-name/${encodeURIComponent(name)}?department=${encodeURIComponent(department ?? '')}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ headcount }),
    errorMessage: '编制人数更新失败',
  })
}
