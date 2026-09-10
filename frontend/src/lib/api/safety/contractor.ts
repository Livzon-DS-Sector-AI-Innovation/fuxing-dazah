import type { Contractor, ContractorQueryParams } from '@/types/safety'
import { apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/** 承包商列表（分页） */
export async function fetchContractorList(
  params?: ContractorQueryParams,
): Promise<{ items: Contractor[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.status) sp.set('status', params.status)
  if (params?.qualification_type) sp.set('qualification_type', params.qualification_type)
  if (params?.training_status) sp.set('training_status', params.training_status)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(`${API_BASE_URL}/api/v1/safety/contractors${qs ? `?${qs}` : ''}`)
}
