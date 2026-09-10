import type {
  SpecialOperationReport,
  SpecialOperationLedgerQueryParams,
  SpecialOperationLedgerStats,
  SpecialOperationPersonnel,
  SpecialOperationPersonnelQueryParams,
} from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 特殊作业台账（分页） */
export async function fetchSpecialOperationLedger(
  params?: SpecialOperationLedgerQueryParams,
): Promise<{ items: SpecialOperationReport[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.operation_type) sp.set('operation_type', params.operation_type)
  if (params?.operation_level) sp.set('operation_level', params.operation_level)
  if (params?.risk_level) sp.set('risk_level', params.risk_level)
  if (params?.department) sp.set('department', params.department)
  if (params?.date_from) sp.set('date_from', params.date_from)
  if (params?.date_to) sp.set('date_to', params.date_to)
  if (params?.keyword) sp.set('keyword', params.keyword)
  if (params?.is_critical !== undefined) sp.set('is_critical', String(params.is_critical))
  const qs = sp.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/special-operation-ledger${qs ? `?${qs}` : ''}`)
}

/** 特殊作业台账统计 */
export async function fetchSpecialOperationLedgerStats(): Promise<SpecialOperationLedgerStats[]> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/special-operation-ledger/stats`)
}

/** 特殊作业人员（分页） */
export async function fetchSpecialOperationPersonnel(
  params?: SpecialOperationPersonnelQueryParams,
): Promise<{ items: SpecialOperationPersonnel[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', params.status)
  if (params?.certificate_type) sp.set('certificate_type', params.certificate_type)
  if (params?.department) sp.set('department', params.department)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/special-operation-personnel' + (qs ? '?' + qs : ''))
}
