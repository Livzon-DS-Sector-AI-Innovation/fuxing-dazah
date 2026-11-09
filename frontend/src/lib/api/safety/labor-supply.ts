import type { LaborSupplyProductsData } from '@/types/safety'
import { apiGet, API_BASE_URL } from '@/lib/http-client'

export interface LaborProductsQueryParams {
  protection_type?: string
  category?: string
  keyword?: string
  page?: number
  page_size?: number
}

/** 劳保用品目录（直读 Bitable；102 行量级，page_size=200 全量拉取客户端过滤） */
export async function fetchLaborProducts(
  params?: LaborProductsQueryParams,
): Promise<LaborSupplyProductsData> {
  const sp = new URLSearchParams()
  if (params?.protection_type) sp.set('protection_type', params.protection_type)
  if (params?.category) sp.set('category', params.category)
  if (params?.keyword) sp.set('keyword', params.keyword)
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiGet(API_BASE_URL + '/api/v1/safety/labor-supply/products' + (qs ? '?' + qs : ''))
}

/** 劳保用品附件代理下载地址（检测报告/说明书；新窗口打开由浏览器下载） */
export function laborAttachmentUrl(
  recordId: string,
  fieldName: '检测报告' | '说明书/产品介绍',
  fileToken: string,
): string {
  const sp = new URLSearchParams({ field_name: fieldName, file_token: fileToken })
  return (
    API_BASE_URL +
    `/api/v1/safety/labor-supply/attachments/${encodeURIComponent(recordId)}?${sp.toString()}`
  )
}
