import type { EhsChange, EhsChangeQueryParams, EhsChangeStats, URSReport, URSQueryParams, URSStats } from '@/types/safety'
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/** EHS 变更台账（分页） */
export async function fetchEhsChanges(
  params?: EhsChangeQueryParams,
): Promise<{ items: EhsChange[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', params.status)
  if (params?.change_type) sp.set('change_type', params.change_type)
  if (params?.change_grade) sp.set('change_grade', params.change_grade)
  if (params?.change_duration) sp.set('change_duration', params.change_duration)
  if (params?.department) sp.set('department', params.department)
  if (params?.keyword) sp.set('keyword', params.keyword)
  if (params?.source) sp.set('source', params.source)
  if (params?.feishu_table_id) sp.set('feishu_table_id', params.feishu_table_id)
  if (params?.sort_by) sp.set('sort_by', params.sort_by)
  if (params?.sort_order) sp.set('sort_order', params.sort_order)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/ehs-changes' + (qs ? '?' + qs : ''))
}

/** EHS 变更统计 */
export async function fetchEhsChangeStats(feishuTableId: string): Promise<EhsChangeStats> {
  const sp = new URLSearchParams()
  if (feishuTableId) sp.set('feishu_table_id', feishuTableId)
  const qs = sp.toString()
  return apiGet(API_BASE_URL + '/api/v1/safety/ehs-changes/stats' + (qs ? '?' + qs : ''))
}

/** URS 报告列表（分页） */
export async function fetchURsReports(
  params?: URSQueryParams,
): Promise<{ items: URSReport[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.department) sp.set('department', params.department)
  if (params?.equipment_category) sp.set('equipment_category', params.equipment_category)
  if (params?.status) sp.set('status', params.status)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/urs-reports' + (qs ? '?' + qs : ''))
}

/** URS 统计 */
export async function fetchURsStats(): Promise<URSStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/urs-reports/stats')
}
