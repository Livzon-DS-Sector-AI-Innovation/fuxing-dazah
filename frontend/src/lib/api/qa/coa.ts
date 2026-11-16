'use client'

import { apiGet } from '@/lib/http-client'
import type {
  CoaMatrix,
  CoaProduct,
  CoaReport,
  CoaReportImportPreview,
  CoaStandard,
  CoaStandardImportPreview,
} from '@/types/qa'

// 浏览器优先走 Next rewrite；服务端调用使用显式后端地址（与 apr 同口径）。
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window === 'undefined' ? 'http://localhost:8000' : '')
const COA_BASE = `${API_BASE}/api/v1/qa/coa`

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export async function fetchCoaProducts(activeOnly = false): Promise<CoaProduct[]> {
  return apiGet<CoaProduct[]>(`${COA_BASE}/products${qs({ active_only: activeOnly })}`)
}

export async function fetchCoaStandards(
  productId?: string,
  activeOnly = false
): Promise<CoaStandard[]> {
  return apiGet<CoaStandard[]>(
    `${COA_BASE}/standards${qs({ product_id: productId, active_only: activeOnly })}`
  )
}

export async function fetchCoaStandardDetail(standardId: string): Promise<CoaStandard> {
  return apiGet<CoaStandard>(`${COA_BASE}/standards/${standardId}`)
}

export async function fetchCoaReportDetail(reportId: string): Promise<CoaReport> {
  return apiGet<CoaReport>(`${COA_BASE}/reports/${reportId}`)
}

export async function fetchCoaMatrix(productId: string): Promise<CoaMatrix> {
  return apiGet<CoaMatrix>(`${COA_BASE}/reports/matrix${qs({ product_id: productId })}`)
}

/** docx → 客户标准草稿预览（不落库）。客户端直传 FormData（Server Action 有 1MB 限制）。 */
export async function importCoaStandardPreview(file: File): Promise<CoaStandardImportPreview> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${COA_BASE}/standards/import-preview`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `解析失败: ${res.status}` }))
    throw new Error(err.message || `解析失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}

/** docx → 报告导入预览（标准匹配 + 项目对齐 + 值预填，不落库）。 */
export async function importCoaReportPreview(
  file: File,
  standardId?: string | null
): Promise<CoaReportImportPreview> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(
    `${COA_BASE}/reports/import-preview${qs({ standard_id: standardId })}`,
    { method: 'POST', body: formData, credentials: 'include' }
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: `解析失败: ${res.status}` }))
    throw new Error(err.message || `解析失败: ${res.status}`)
  }
  const json = await res.json()
  return json.data ?? json
}
