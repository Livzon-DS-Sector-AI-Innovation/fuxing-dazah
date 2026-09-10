import type {
  KeyRiskOperationReport,
  KeyRiskOperationQueryParams,
  KeyRiskOperationLedgerStats,
} from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 关键风险作业报备（分页） */
export async function fetchKeyRiskOperationReports(
  params?: KeyRiskOperationQueryParams,
): Promise<{ items: KeyRiskOperationReport[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.department) sp.set('department', params.department)
  if (params?.area) sp.set('area', params.area)
  if (params?.operation_content) sp.set('operation_content', params.operation_content)
  if (params?.apply_status) sp.set('apply_status', params.apply_status)
  if (params?.date_from) sp.set('date_from', params.date_from)
  if (params?.date_to) sp.set('date_to', params.date_to)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/key-risk-operation-reports' + (qs ? '?' + qs : ''))
}

/** 关键风险作业统计 */
export async function fetchKeyRiskOperationStats(): Promise<KeyRiskOperationLedgerStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/key-risk-operation-reports/stats')
}
