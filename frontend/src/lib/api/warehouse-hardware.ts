// 五金库 API 请求函数（系统原生仓储域，本地 DB 权威）
// 双基址模式照抄 lib/api/warehouse.ts：SERVER_API 供 Server Actions/Server
// Component，CLIENT_API 供 'use client' 组件直连。

import { apiGet, apiFetchPaginated, apiPost } from '@/lib/http-client'
import type {
  HardwareStockRow,
  HardwareStockFilter,
  HardwareStockSummary,
  HardwareMaterialRecord,
  HardwareLotRow,
  HardwareMovementRecord,
  HardwareMovementFilter,
  HardwareReceiptRecord,
  HardwareReceiptFilter,
  HardwareReceiptCreateInput,
  HardwareReceiptAcceptInput,
  HardwareRequisitionRecord,
  HardwareRequisitionFilter,
  HardwareRequisitionCreateInput,
  HardwareRequisitionIssueInput,
  HardwareLocationRecord,
  HardwareImportStats,
} from '@/types/warehouse-hardware'

const SERVER_API = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const CLIENT_API = process.env.NEXT_PUBLIC_API_BASE_URL || ''
const BASE = '/api/v1/warehouse/hardware'

// ── 库存总览 ──

function setStockParams(sp: URLSearchParams, params: HardwareStockFilter) {
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.category) sp.set('category', params.category)
  if (params.managed_class !== undefined) sp.set('managed_class', params.managed_class)
  if (params.low_only) sp.set('low_only', 'true')
  sp.set('page', String(params.page ?? 1))
  sp.set('page_size', String(params.pageSize ?? 20))
}

export async function fetchHardwareStock(
  params: HardwareStockFilter = {},
): Promise<PaginatedCompat<HardwareStockRow>> {
  const sp = new URLSearchParams()
  setStockParams(sp, params)
  return apiFetchPaginated<HardwareStockRow>(`${SERVER_API}${BASE}/stock?${sp.toString()}`)
}

export async function fetchHardwareStockClient(
  params: HardwareStockFilter = {},
): Promise<PaginatedCompat<HardwareStockRow>> {
  const sp = new URLSearchParams()
  setStockParams(sp, params)
  return apiFetchPaginated<HardwareStockRow>(`${CLIENT_API}${BASE}/stock?${sp.toString()}`)
}

export async function fetchHardwareStockSummaryClient(): Promise<HardwareStockSummary> {
  return apiGet<HardwareStockSummary>(`${CLIENT_API}${BASE}/stock/summary`)
}

export interface HardwareStockDetail {
  stock: HardwareStockRow
  lots: HardwareLotRow[]
  recent_movements: HardwareMovementRecord[]
}

export async function fetchHardwareStockDetailClient(
  materialId: string,
): Promise<HardwareStockDetail> {
  return apiGet<HardwareStockDetail>(`${CLIENT_API}${BASE}/stock/${materialId}`)
}

export async function fetchHardwareFifoSuggestionClient(
  materialId: string,
  qty: number | string,
): Promise<Array<{ lot_no?: string; allocate?: number; shortage?: number }>> {
  return apiGet(`${CLIENT_API}${BASE}/stock/${materialId}/fifo-suggestion?qty=${qty}`)
}

// ── 物料/库位 ──

export async function fetchHardwareMaterialsClient(
  keyword = '', pageSize = 50,
): Promise<PaginatedCompat<HardwareMaterialRecord>> {
  const sp = new URLSearchParams()
  if (keyword) sp.set('keyword', keyword)
  sp.set('page', '1')
  sp.set('page_size', String(pageSize))
  return apiFetchPaginated<HardwareMaterialRecord>(`${CLIENT_API}${BASE}/materials?${sp.toString()}`)
}

export async function fetchHardwareLocationsClient(): Promise<HardwareLocationRecord[]> {
  return apiGet<HardwareLocationRecord[]>(`${CLIENT_API}${BASE}/locations`)
}

export async function importHardwareMaterials(file: File): Promise<HardwareImportStats> {
  const form = new FormData()
  form.append('file', file)
  const base = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  const resp = await fetch(`${base}${BASE}/materials/import`, {
    method: 'POST',
    body: form,
    credentials: 'include',
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    throw new Error(body?.message || `导入失败 (${resp.status})`)
  }
  const json = await resp.json()
  return (json as { data?: HardwareImportStats })?.data ?? (json as HardwareImportStats)
}

// ── 入库单 ──

function setReceiptParams(sp: URLSearchParams, params: HardwareReceiptFilter) {
  if (params.status) sp.set('status', params.status)
  if (params.source) sp.set('source', params.source)
  if (params.keyword) sp.set('keyword', params.keyword)
  sp.set('page', String(params.page ?? 1))
  sp.set('page_size', String(params.pageSize ?? 20))
}

export async function fetchHardwareReceiptsClient(
  params: HardwareReceiptFilter = {},
): Promise<PaginatedCompat<HardwareReceiptRecord>> {
  const sp = new URLSearchParams()
  setReceiptParams(sp, params)
  return apiFetchPaginated<HardwareReceiptRecord>(`${CLIENT_API}${BASE}/receipts?${sp.toString()}`)
}

export async function createHardwareReceiptClient(
  payload: HardwareReceiptCreateInput,
): Promise<HardwareReceiptRecord> {
  return apiPost<HardwareReceiptRecord>(`${CLIENT_API}${BASE}/receipts`, payload)
}

export async function acceptHardwareReceiptClient(
  receiptId: string,
  payload: HardwareReceiptAcceptInput,
): Promise<HardwareReceiptRecord> {
  return apiPost<HardwareReceiptRecord>(`${CLIENT_API}${BASE}/receipts/${receiptId}/accept`, payload)
}

export async function rejectHardwareReceiptClient(
  receiptId: string,
  reason: string,
): Promise<HardwareReceiptRecord> {
  return apiPost<HardwareReceiptRecord>(`${CLIENT_API}${BASE}/receipts/${receiptId}/reject`, { reason })
}

// ── 领用申请 ──

function setRequisitionParams(sp: URLSearchParams, params: HardwareRequisitionFilter) {
  if (params.status) sp.set('status', params.status)
  if (params.dept_name) sp.set('dept_name', params.dept_name)
  if (params.req_type) sp.set('req_type', params.req_type)
  if (params.keyword) sp.set('keyword', params.keyword)
  sp.set('page', String(params.page ?? 1))
  sp.set('page_size', String(params.pageSize ?? 20))
}

export async function fetchHardwareRequisitionsClient(
  params: HardwareRequisitionFilter = {},
): Promise<PaginatedCompat<HardwareRequisitionRecord>> {
  const sp = new URLSearchParams()
  setRequisitionParams(sp, params)
  return apiFetchPaginated<HardwareRequisitionRecord>(`${CLIENT_API}${BASE}/requisitions?${sp.toString()}`)
}

export async function createHardwareRequisitionClient(
  payload: HardwareRequisitionCreateInput,
): Promise<HardwareRequisitionRecord> {
  return apiPost<HardwareRequisitionRecord>(`${CLIENT_API}${BASE}/requisitions`, payload)
}

export async function submitHardwareRequisitionClient(id: string): Promise<HardwareRequisitionRecord> {
  return apiPost<HardwareRequisitionRecord>(`${CLIENT_API}${BASE}/requisitions/${id}/submit`, {})
}

export async function approveHardwareRequisitionClient(
  id: string, approver: string, note?: string,
): Promise<HardwareRequisitionRecord> {
  return apiPost<HardwareRequisitionRecord>(`${CLIENT_API}${BASE}/requisitions/${id}/approve`, { approver, note })
}

export async function rejectHardwareRequisitionClient(
  id: string, approver: string, reason: string,
): Promise<HardwareRequisitionRecord> {
  return apiPost<HardwareRequisitionRecord>(`${CLIENT_API}${BASE}/requisitions/${id}/reject`, { approver, reason })
}

export async function cancelHardwareRequisitionClient(id: string): Promise<HardwareRequisitionRecord> {
  return apiPost<HardwareRequisitionRecord>(`${CLIENT_API}${BASE}/requisitions/${id}/cancel`, {})
}

export async function issueHardwareRequisitionClient(
  id: string, payload: HardwareRequisitionIssueInput,
): Promise<HardwareRequisitionRecord> {
  return apiPost<HardwareRequisitionRecord>(`${CLIENT_API}${BASE}/requisitions/${id}/issue`, payload)
}

// ── 流水 ──

export function fetchHardwareMovementsClient(
  params: HardwareMovementFilter = {},
): Promise<PaginatedCompat<HardwareMovementRecord>> {
  const sp = new URLSearchParams()
  if (params.direction) sp.set('direction', params.direction)
  if (params.business_type) sp.set('business_type', params.business_type)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.dept_name) sp.set('dept_name', params.dept_name)
  if (params.erp_status) sp.set('erp_status', params.erp_status)
  sp.set('page', String(params.page ?? 1))
  sp.set('page_size', String(params.pageSize ?? 20))
  return apiFetchPaginated<HardwareMovementRecord>(`${CLIENT_API}${BASE}/movements?${sp.toString()}`)
}

export async function markHardwareMovementsEnteredClient(
  movementIds: string[], erpOperator?: string,
): Promise<{ marked: number }> {
  return apiPost<{ marked: number }>(`${CLIENT_API}${BASE}/movements/mark-entered`, {
    movement_ids: movementIds,
    erp_operator: erpOperator,
  })
}

// 与 types/warehouse.ts 同名的分页壳（本文件局部，避免跨模块耦合）
interface PaginatedCompat<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
