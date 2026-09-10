import type { MsdsDocument, MsdsDocumentQueryParams, MsdsStats, MsdsCollectionRecord, MsdsCollectionQueryParams } from '@/types/safety'
import { apiGet, apiFetchPaginated, API_BASE_URL } from '@/lib/http-client'


/** MSDS 台账（分页） */
export async function fetchMsdsDocuments(
  params?: MsdsDocumentQueryParams,
): Promise<{ items: MsdsDocument[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.name) sp.set('name', params.name)
  if (params?.cas_no) sp.set('cas_no', params.cas_no)
  if (params?.review_status) sp.set('review_status', params.review_status)
  if (params?.archive_status) sp.set('archive_status', params.archive_status)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/msds' + (qs ? '?' + qs : ''))
}

/** MSDS 统计 */
export async function fetchMsdsStats(): Promise<MsdsStats> {
  return apiGet(API_BASE_URL + '/api/v1/safety/msds/stats')
}

/** MSDS 采集记录（分页） */
export async function fetchMsdsCollections(
  params?: MsdsCollectionQueryParams,
): Promise<{ items: MsdsCollectionRecord[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  if (params?.parse_status) sp.set('parse_status', params.parse_status)
  if (params?.keyword) sp.set('keyword', params.keyword)
  const qs = sp.toString()
  return apiFetchPaginated(API_BASE_URL + '/api/v1/safety/msds/collection' + (qs ? '?' + qs : ''))
}
