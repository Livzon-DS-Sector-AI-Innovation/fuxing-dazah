'use client'

import { apiFetchPaginated, apiGet } from '@/lib/http-client'
import type {
  AprAnnualReview,
  AprBatch,
  AprBatchValuesPayload,
  AprDataKind,
  AprProduct,
  AprSection,
  AprSummary,
  AprTrend,
} from '@/types/qa-apr'

// 浏览器优先走 Next rewrite；服务端调用使用显式后端地址（与 qa-deviation 同口径）。
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window === 'undefined' ? 'http://localhost:8000' : '')
const APR_BASE = `${API_BASE}/api/v1/qa/apr`

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export async function fetchAprProducts(activeOnly = false): Promise<AprProduct[]> {
  return apiGet<AprProduct[]>(`${APR_BASE}/products${qs({ active_only: activeOnly })}`)
}

export async function fetchAprSections(productId: string): Promise<AprSection[]> {
  return apiGet<AprSection[]>(`${APR_BASE}/sections${qs({ product_id: productId })}`)
}

export async function fetchAprBatches(params: {
  section_id: string
  year?: number
  keyword?: string
  page?: number
  page_size?: number
}) {
  return apiFetchPaginated<AprBatch>(`${APR_BASE}/batches${qs({ ...params })}`)
}

export async function fetchAprBatchValues(batchId: string): Promise<AprBatchValuesPayload> {
  return apiGet<AprBatchValuesPayload>(`${APR_BASE}/batches/${batchId}/values`)
}

export async function fetchAprTrend(itemId: string, year?: number): Promise<AprTrend> {
  return apiGet<AprTrend>(`${APR_BASE}/trends${qs({ item_id: itemId, year })}`)
}

export async function fetchAprSummary(params: {
  product_id: string
  year: number
  data_kind?: AprDataKind
  market?: string
}): Promise<AprSummary> {
  return apiGet<AprSummary>(`${APR_BASE}/summary${qs({ ...params })}`)
}

export async function fetchAprAnnualReviews(productId: string): Promise<AprAnnualReview[]> {
  return apiGet<AprAnnualReview[]>(`${APR_BASE}/annual-reviews${qs({ product_id: productId })}`)
}

/** 汇总导出直链（浏览器同源 cookie 鉴权，供 <a download> 使用）。 */
export function aprSummaryExportUrl(productId: string, year: number): string {
  return `${APR_BASE}/summary/export${qs({ product_id: productId, year })}`
}
