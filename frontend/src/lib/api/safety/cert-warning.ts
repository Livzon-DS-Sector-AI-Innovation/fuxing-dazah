import type { CertWarningDetail, CertWarningQueryParams, CertWarningSummary } from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** 持证到期预警明细（分页） */
export async function fetchCertWarnings(
  params?: CertWarningQueryParams,
): Promise<{ items: CertWarningDetail[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status_level) sp.set('status_level', String(params.status_level))
  if (params?.department) sp.set('department', params.department)
  if (params?.cert_category) sp.set('cert_category', String(params.cert_category))
  if (params?.days_within !== undefined) sp.set('days_within', String(params.days_within))
  const qs = sp.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/cert-warnings${qs ? `?${qs}` : ''}`)
}

/** 持证到期预警汇总 */
export async function fetchCertWarningSummary(
  params?: { department?: string; cert_category?: string },
): Promise<CertWarningSummary> {
  const sp = new URLSearchParams()
  if (params?.department) sp.set('department', params.department)
  if (params?.cert_category) sp.set('cert_category', params.cert_category)
  const qs = sp.toString()
  return apiGet(`${API_BASE_URL}/api/v1/safety/cert-warnings/summary${qs ? `?${qs}` : ''}`)
}
