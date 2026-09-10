import type { FireAlarmRecord, FireAlarmQueryParams, FireAlarmStats } from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 消防报警记录（分页） */
export async function fetchFireAlarmRecords(
  params?: FireAlarmQueryParams,
): Promise<{ items: FireAlarmRecord[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.date_from) sp.set('date_from', params.date_from)
  if (params?.date_to) sp.set('date_to', params.date_to)
  if (params?.department) sp.set('department', params.department)
  if (params?.alarm_type) sp.set('alarm_type', params.alarm_type)
  if (params?.alarm_nature) sp.set('alarm_nature', params.alarm_nature)
  if (params?.ai_dimension) sp.set('ai_dimension', params.ai_dimension)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/fire-alarms/records${qs ? `?${qs}` : ''}`)
}

/** 消防报警 KPI 统计 */
export async function fetchFireAlarmStats(): Promise<FireAlarmStats> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/fire-alarms/stats`)
}
