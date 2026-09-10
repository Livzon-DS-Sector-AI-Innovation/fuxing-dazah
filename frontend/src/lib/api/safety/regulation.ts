import type { OperationRegulation, OperationRegulationQueryParams, RegulationRevision, RegulationRevisionQueryParams } from '@/types/safety'
import { apiFetchPaginated } from '@/lib/http-client'

const API_BASE_URL = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/** 安全操作规程列表（分页） */
export async function fetchRegulations(
  params?: OperationRegulationQueryParams,
): Promise<{ items: OperationRegulation[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.position) sp.set('position', params.position)
  if (params?.keyword) sp.set('keyword', params.keyword)
  if (params?.status) sp.set('status', params.status)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/regulations' + (qs ? '?' + qs : ''))
}

/** 修订记录列表（分页） */
export async function fetchRevisions(
  params?: RegulationRevisionQueryParams,
): Promise<{ items: RegulationRevision[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.regulation_id) sp.set('regulation_id', params.regulation_id)
  if (params?.revision_type) sp.set('revision_type', params.revision_type)
  if (params?.review_opinion) sp.set('review_opinion', params.review_opinion)
  if (params?.revision_scope) sp.set('revision_scope', params.revision_scope)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/revisions' + (qs ? '?' + qs : ''))
}
