import type { ContractorAdmissionListItem, ContractorAdmissionQueryParams, ContractorAdmissionStats } from '@/types/safety'
import { apiGet, apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/** 相关方准入列表（分页） */
export async function fetchContractorAdmissions(
  params?: ContractorAdmissionQueryParams,
): Promise<{ items: ContractorAdmissionListItem[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.related_party_type) sp.set('related_party_type', params.related_party_type)
  if (params?.submit_status) sp.set('submit_status', params.submit_status)
  if (params?.ai_review_status) sp.set('ai_review_status', params.ai_review_status)
  if (params?.ai_conclusion) sp.set('ai_conclusion', params.ai_conclusion)
  if (params?.keyword) sp.set('keyword', params.keyword)
  if (params?.sort_by) sp.set('sort_by', params.sort_by)
  if (params?.sort_order) sp.set('sort_order', params.sort_order)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/contractor-admissions' + (qs ? '?' + qs : ''))
}

/** 相关方准入 KPI 统计 */
export async function fetchContractorAdmissionStats(): Promise<ContractorAdmissionStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/contractor-admissions/stats')
}
