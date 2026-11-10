'use server'

import { revalidatePath } from 'next/cache'
import type { EmployeeSyncConfig, EmployeeSyncStats } from '@/types/hr'
import { fetchHrApi } from './_helpers'

// ─── 员工档案多维表格同步 ───

export async function fetchEmployeeSyncConfig(): Promise<{ data: EmployeeSyncConfig }> {
  return fetchHrApi('/hr/employee-sync/config', { errorMessage: '加载员工档案同步配置失败' })
}

export async function saveEmployeeSyncConfig(input: {
  enabled: boolean
  app_token: string
  source_table_id: string
  training_table_id?: string | null
}): Promise<{ data: EmployeeSyncConfig; message: string }> {
  const res = await fetchHrApi<{ data: EmployeeSyncConfig; message: string }>(
    '/hr/employee-sync/config',
    {
      method: 'PUT',
      body: JSON.stringify(input),
      errorMessage: '保存同步配置失败',
    },
  )
  revalidatePath('/hr/settings')
  revalidatePath('/hr/profile')
  return res
}

export async function triggerEmployeeSync(): Promise<{ data: EmployeeSyncStats; message: string }> {
  const res = await fetchHrApi<{ data: EmployeeSyncStats; message: string }>(
    '/hr/employee-sync/sync',
    { method: 'POST', errorMessage: '同步失败' },
  )
  revalidatePath('/hr/profile')
  return res
}

export interface TrainingRosterRow {
  employee_number: string
  name: string
  department: string
  actual_department?: string | null
  team?: string | null
  position: string
  duty?: string | null
  job_category?: string | null
  variety?: string | null
  concurrent_departments?: string | null
  concurrent_variety?: string | null
  education?: string | null
  graduation_date?: string | null
  status_category?: string | null
  status: string
  work_start_date?: string | null
  factory_entry_date?: string | null
  livo_entry_date?: string | null
  hire_date?: string | null
  departure_date?: string | null
  certificates?: string | null
  qualifications?: string[] | null
  training_id?: string | null
  dept_head_trainer?: string | null
  safety_training_date?: string | null
  safety_training_score?: string | null
  culture_training_date?: string | null
  gmp_training_date?: string | null
}

export async function fetchTrainingRoster(params?: {
  department?: string
  keyword?: string
  page?: number
  page_size?: number
}): Promise<{ data: TrainingRosterRow[]; meta?: { total: number; scoped_departments?: string[] | null } }> {
  const qs = new URLSearchParams()
  if (params?.department) qs.set('department', params.department)
  if (params?.keyword) qs.set('keyword', params.keyword)
  if (params?.page) qs.set('page', String(params.page))
  qs.set('page_size', String(params?.page_size ?? 20))
  return fetchHrApi(`/hr/employee-sync/training-roster?${qs.toString()}`, {
    errorMessage: '加载培训人员名单失败',
  })
}

export async function updateTrainingRosterEntry(
  employee_number: string,
  data: Partial<TrainingRosterRow>,
): Promise<{ message: string }> {
  const res = await fetchHrApi<{ message: string }>(
    `/hr/employee-sync/training-roster/${encodeURIComponent(employee_number)}`,
    {
      method: 'PUT',
      body: JSON.stringify(data),
      errorMessage: '保存失败',
    },
  )
  revalidatePath('/hr/training/personnel')
  return res
}
