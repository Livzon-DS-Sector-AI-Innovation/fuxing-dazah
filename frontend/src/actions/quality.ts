'use server'

import { revalidatePath } from 'next/cache'
import { getServerToken, getImpersonateToken } from '@/lib/auth'
import type {
  UploadLcResponse,
  InspectionRecordListItem,
  InspectionRecordDetail,
  ReportRecord,
  HistorySummary,
} from '@/types/quality'

const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000'

/**
 * 上传液相计算表 Excel 并获取解析结果。
 * 使用 FormData 传输文件，不能设 Content-Type（让浏览器自动处理 boundary）。
 */
export async function uploadLcExcel(formData: FormData): Promise<UploadLcResponse> {
  const token = await getServerToken()
  const impToken = await getImpersonateToken()

  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`

  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/upload`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || (err as any).message || '上传解析失败')
  }

  revalidatePath('/quality')
  return res.json()
}


async function _authHeaders(): Promise<Record<string, string>> {
  const token = await getServerToken()
  const impToken = await getImpersonateToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (impToken) headers['Cookie'] = `impersonate_token=${impToken}`
  return headers
}

/** 分页查询液相解析历史记录 */
export async function fetchInspectionRecords(
  product_name?: string,
  batch_number?: string,
  page = 1,
): Promise<{ data: InspectionRecordListItem[]; meta: { total: number } }> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (batch_number) qs.set('batch_number', batch_number)
  qs.set('page', String(page))
  qs.set('page_size', '20')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/records?${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取检验记录失败')
  return res.json()
}

/** 查询单条检验记录详情（含杂质明细） */
export async function fetchInspectionRecord(id: string): Promise<InspectionRecordDetail> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/records/${id}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取检验记录详情失败')
  const body = await res.json()
  return body.data as InspectionRecordDetail
}

/** 删除检验记录（软删除） */
export async function deleteInspectionRecord(id: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/lc/records/${id}`, {
    method: 'DELETE', headers: await _authHeaders(),
  })
  if (!res.ok) throw new Error('删除失败')
  return res.json()
}

/** 报告单历史列表 */
export async function fetchReportRecords(
  product_name?: string,
  batch_number?: string,
  page = 1,
): Promise<{ data: ReportRecord[]; meta: { total: number } }> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (batch_number) qs.set('batch_number', batch_number)
  qs.set('page', String(page))
  qs.set('page_size', '20')
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/records?${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取报告单记录失败')
  return res.json()
}

/** 生成报告单（返回原始响应，调用方按 blob 下载） */
export async function generateReport(recordId: string, template: string): Promise<Response> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/report/generate`, {
    method: 'POST',
    headers: { ...(await _authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ inspection_record_id: recordId, template }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as any).detail || '生成报告单失败')
  }
  return res
}

/** 多批次历史汇总 */
export async function fetchHistorySummary(
  product_name?: string,
  date_from?: string,
  date_to?: string,
): Promise<HistorySummary> {
  const qs = new URLSearchParams()
  if (product_name) qs.set('product_name', product_name)
  if (date_from) qs.set('date_from', date_from)
  if (date_to) qs.set('date_to', date_to)
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/history?${qs}`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取汇总失败')
  const body = await res.json()
  return body.data as HistorySummary
}

/** 已检验产品列表 */
export async function fetchSummaryProducts(): Promise<string[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/quality/summary/products`, {
    headers: await _authHeaders(), cache: 'no-store',
  })
  if (!res.ok) throw new Error('获取产品列表失败')
  const body = await res.json()
  return body.data as string[]
}
