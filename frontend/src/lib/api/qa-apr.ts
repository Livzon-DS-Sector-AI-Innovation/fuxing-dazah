'use client'

import { apiFetchPaginated, apiGet } from '@/lib/http-client'
import type {
  AprAnnualReview,
  AprBatch,
  AprBatchValuesPayload,
  AprDataKind,
  AprImportMode,
  AprImportResult,
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

/** 段级汇总导出直链（该段模板数据+全量统计，浏览器同源 cookie 鉴权）。 */
export function aprSectionExportUrl(sectionId: string, year: number): string {
  return `${APR_BASE}/sections/${sectionId}/export${qs({ year })}`
}

/** 录入导入模板直链（同上，<a download> 下载）。 */
export function aprImportTemplateUrl(sectionId: string, year: number): string {
  return `${APR_BASE}/sections/${sectionId}/import-template${qs({ year })}`
}

/** 段级年度回顾 Word 报告直链（趋势图+CPK 结论）。 */
export function aprSectionReportUrl(sectionId: string, year: number): string {
  return `${APR_BASE}/sections/${sectionId}/report${qs({ year })}`
}

/** Excel 批量导入录入值。客户端直传 FormData（Server Action 有 1MB body 限制）。 */
export async function importAprSectionValues(
  sectionId: string,
  year: number,
  mode: AprImportMode,
  file: File
): Promise<AprImportResult> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(
    `${APR_BASE}/sections/${sectionId}/values/import${qs({ year, mode })}`,
    { method: 'POST', body: formData, credentials: 'include' }
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `导入失败: ${res.status}` }))
    throw new Error(err.message || `导入失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}
