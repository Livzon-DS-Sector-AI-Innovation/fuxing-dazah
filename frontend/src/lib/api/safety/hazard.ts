import type { HazardReport, HazardReportQueryParams, HazardStats } from '@/types/safety'
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/** 隐患排查台账（分页） */
export async function fetchHazards(
  params?: HazardReportQueryParams,
): Promise<{ items: HazardReport[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', params.status)
  if (params?.rectification_status) sp.set('rectification_status', params.rectification_status)
  if (params?.overall_status) sp.set('overall_status', params.overall_status)
  if (params?.hazard_type) sp.set('hazard_type', params.hazard_type)
  if (params?.hazard_level) sp.set('hazard_level', params.hazard_level)
  if (params?.hazard_category) sp.set('hazard_category', params.hazard_category)
  if (params?.inspection_category) sp.set('inspection_category', params.inspection_category)
  if (params?.department) sp.set('department', params.department)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/hazards' + (qs ? '?' + qs : ''))
}

/** 隐患排查统计 */
export async function fetchHazardStats(): Promise<HazardStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/hazards/stats')
}
