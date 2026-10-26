'use client'

import { apiFetchPaginated, apiGet } from '@/lib/http-client'
import type {
  CapaBrief,
  CapaDetail,
  CapaListParams,
  CapaStatus,
  DeviationBrief,
  DeviationDetail,
  DeviationListParams,
  DeviationStatus,
} from '@/types/qa-deviation'

// 浏览器优先走 Next rewrite，避免跨端口时 httpOnly auth cookie 丢失；
// 服务端调用再使用显式后端地址（与 lib/api/qa.ts 同口径）。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window === 'undefined' ? 'http://localhost:8000' : '')
const QA_BASE = `${API_BASE}/api/v1/qa`

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export async function fetchDeviations(params: DeviationListParams = {}) {
  return apiFetchPaginated<DeviationBrief>(`${QA_BASE}/deviations${qs({ ...params })}`)
}

export async function fetchDeviationSummary(): Promise<Record<DeviationStatus, number>> {
  return apiGet<Record<DeviationStatus, number>>(`${QA_BASE}/deviations/summary`)
}

export async function fetchDeviation(id: string): Promise<DeviationDetail> {
  return apiGet<DeviationDetail>(`${QA_BASE}/deviations/${id}`)
}

/** 附件直链：PDF/图片内联预览，其余下载；浏览器同源 cookie 鉴权。 */
export function deviationAttachmentUrl(deviationId: string, attachmentId: string, download = false): string {
  return `${QA_BASE}/deviations/${deviationId}/attachments/${attachmentId}/content${download ? '?download=true' : ''}`
}

export async function fetchCapas(params: CapaListParams = {}) {
  return apiFetchPaginated<CapaBrief>(`${QA_BASE}/capas${qs({ ...params })}`)
}

export async function fetchCapaSummary(): Promise<Record<CapaStatus, number>> {
  return apiGet<Record<CapaStatus, number>>(`${QA_BASE}/capas/summary`)
}

export async function fetchCapa(id: string): Promise<CapaDetail> {
  return apiGet<CapaDetail>(`${QA_BASE}/capas/${id}`)
}
