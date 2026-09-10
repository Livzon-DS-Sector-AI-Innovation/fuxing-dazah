import type { DrillRecord, DrillRecordQueryParams, DrillStats } from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 应急演练记录（分页） */
export async function fetchDrillRecords(
  params?: DrillRecordQueryParams,
): Promise<{ items: DrillRecord[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.department) sp.set('department', params.department)
  if (params?.drill_type) sp.set('drill_type', params.drill_type)
  if (params?.status) sp.set('status', params.status)
  if (params?.keyword) sp.set('keyword', params.keyword)
  if (params?.stage) sp.set('stage', params.stage)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/emergency-drills' + (qs ? '?' + qs : ''))
}

/** 应急演练统计 */
export async function fetchDrillStats(): Promise<DrillStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/emergency-drills/stats')
}
