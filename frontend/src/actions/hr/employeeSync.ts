'use server'

import { revalidatePath } from 'next/cache'
import type {
  EmployeeSyncConfig, EmployeeSyncStats, RosterFollowConfig, RosterFollowConfigInput,
  RosterFollowMode, RosterFollowPreview, RosterFollowSource,
} from '@/types/hr'
import { fetchHrApi, fetchHrDownload } from './_helpers'

// ─── 员工档案多维表格同步 ───

export async function fetchEmployeeSyncConfig(): Promise<{ data: EmployeeSyncConfig }> {
  return fetchHrApi('/hr/employee-sync/config', { errorMessage: '加载员工档案同步配置失败' })
}

export async function saveEmployeeSyncConfig(input: {
  enabled: boolean
  app_token: string
  source_table_id: string
  headcount_table_id?: string
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
  revalidatePath('/hr/headcount')
  return res
}

export async function triggerEmployeeSync(): Promise<{ data: EmployeeSyncStats; message: string }> {
  const res = await fetchHrApi<{ data: EmployeeSyncStats; message: string }>(
    '/hr/employee-sync/sync',
    { method: 'POST', errorMessage: '同步失败' },
  )
  revalidatePath('/hr/profile')
  revalidatePath('/hr/headcount')
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
  /** 报表用职级：后端按职级（S13及以上）+职务自动计算 */
  report_level?: string | null
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
  /** 人员分类标签名（随名单行下发；不含已移除的） */
  tags?: string[]
  /** 生效的例外模式（空串/缺省 = 跟随全局字段规则） */
  follow_mode?: RosterFollowMode
  /** 例外来源：member 按工号 / department 按名单体现部门（缺省 = 无例外） */
  follow_source?: RosterFollowSource
}

export async function fetchTrainingRoster(params?: {
  department?: string
  keyword?: string
  page?: number
  page_size?: number
}): Promise<{
  data: TrainingRosterRow[]
  meta?: {
    total: number
    scoped_departments?: string[] | null
    /** 全局已设为跟随员工档案的字段 */
    follow_fields?: string[]
    /** 可跟随员工档案的字段范围（档案里没有来源的字段不在此列，只能在名单维护） */
    followable_fields?: string[]
  }
}> {
  const qs = new URLSearchParams()
  if (params?.department) qs.set('department', params.department)
  if (params?.keyword) qs.set('keyword', params.keyword)
  if (params?.page) qs.set('page', String(params.page))
  qs.set('page_size', String(params?.page_size ?? 20))
  return fetchHrApi(`/hr/employee-sync/training-roster?${qs.toString()}`, {
    errorMessage: '加载培训人员名单失败',
  })
}

/** 取全量名单（自动翻页）：选人/通知/统计等无翻页 UI 的场景必须用它，防止超过单页上限时静默漏人。 */
export async function fetchAllTrainingRoster(params?: {
  department?: string
  keyword?: string
}): Promise<{ data: TrainingRosterRow[]; scoped_departments: string[] | null }> {
  const pageSize = 500
  const rows: TrainingRosterRow[] = []
  let scoped: string[] | null = null
  for (let page = 1; ; page += 1) {
    const res = await fetchTrainingRoster({ ...params, page, page_size: pageSize })
    rows.push(...(res.data || []))
    scoped = res.meta?.scoped_departments ?? null
    const total = res.meta?.total ?? 0
    if (!(res.data || []).length || rows.length >= total) break
  }
  return { data: rows, scoped_departments: scoped }
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

export async function fetchTrainingRosterFollowConfig(): Promise<{ data: RosterFollowConfig }> {
  return fetchHrApi('/hr/employee-sync/training-roster/follow-config', {
    errorMessage: '加载名单跟随规则失败',
  })
}

/** 保存名单跟随规则。apply=false 只预览影响（不落库）；apply=true 保存并立即按规则覆盖一遍。
 * 需要系统配置权限（hr:settings:manage）。 */
export async function saveTrainingRosterFollowConfig(
  input: RosterFollowConfigInput,
): Promise<{ data: RosterFollowConfig & { preview: RosterFollowPreview }; message: string }> {
  const res = await fetchHrApi<{ data: RosterFollowConfig & { preview: RosterFollowPreview }; message: string }>(
    '/hr/employee-sync/training-roster/follow-config',
    {
      method: 'PUT',
      body: JSON.stringify(input),
      errorMessage: '保存名单跟随规则失败',
    },
  )
  if (input.apply) revalidatePath('/hr/training/personnel')
  return res
}

/** 导出培训人员名单 Excel（含报表用职级列，按当前筛选范围导出全量）。
 * 只负责取数：返回 base64 + 文件名，文件落地由客户端组件调 downloadBase64File 完成
 * （'use server' 环境无 window，不能在这里触发浏览器下载）。 */
export async function exportTrainingRoster(params?: {
  department?: string
  keyword?: string
}): Promise<{ base64: string; filename: string | null }> {
  const qs = new URLSearchParams()
  if (params?.department) qs.set('department', params.department)
  if (params?.keyword) qs.set('keyword', params.keyword)
  return fetchHrDownload(
    `/hr/employee-sync/training-roster/export?${qs.toString()}`,
    { errorMessage: '下载培训人员名单失败' },
  )
}
