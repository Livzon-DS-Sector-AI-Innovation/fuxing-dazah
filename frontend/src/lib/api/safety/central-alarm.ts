import type { CentralAlarmRecord, CentralAlarmQueryParams, CentralAlarmStats } from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 中控报警记录（分页） */
export async function fetchCentralAlarmRecords(
  params?: CentralAlarmQueryParams,
): Promise<{ items: CentralAlarmRecord[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.date_from) sp.set('date_from', params.date_from)
  if (params?.date_to) sp.set('date_to', params.date_to)
  if (params?.workshop) sp.set('workshop', params.workshop)
  if (params?.line) sp.set('line', params.line)
  if (params?.post) sp.set('post', params.post)
  if (params?.ai_alarm_type) sp.set('ai_alarm_type', params.ai_alarm_type)
  if (params?.ai_dimension) sp.set('ai_dimension', params.ai_dimension)
  if (params?.ai_pattern) sp.set('ai_pattern', params.ai_pattern)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/central-alarms/records${qs ? `?${qs}` : ''}`)
}

/** 中控报警 KPI 统计 */
export async function fetchCentralAlarmStats(): Promise<CentralAlarmStats> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/central-alarms/stats`)
}
