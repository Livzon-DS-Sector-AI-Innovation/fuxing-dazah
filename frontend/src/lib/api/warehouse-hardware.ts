// 五金库 API 请求函数（系统原生仓储域，本地 DB 权威）
// 双基址模式照抄 lib/api/warehouse.ts：SERVER_API 供 Server Actions/Server
// Component，CLIENT_API 供 'use client' 组件直连。

import { apiGet, apiFetchPaginated, apiPost, apiPut } from '@/lib/http-client'
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
  HardwareStocktakeRecord,
  HardwareStocktakeItemRecord,
  HardwareReturnRecord,
  HardwarePlanRecord,
  HardwarePlanItemRecord,
  HardwareEnvLogRecord,
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


// ── 盘点（二期 M4）──

export interface HardwareStocktakeFilter {
  status?: string
  take_type?: string
  page?: number
  pageSize?: number
}

export async function fetchHardwareStocktakesClient(
  params: HardwareStocktakeFilter = {},
): Promise<PaginatedCompat<HardwareStocktakeRecord>> {
  const sp = new URLSearchParams()
  if (params.status) sp.set('status', params.status)
  if (params.take_type) sp.set('take_type', params.take_type)
  sp.set('page', String(params.page ?? 1))
  sp.set('page_size', String(params.pageSize ?? 20))
  return apiFetchPaginated<HardwareStocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes?${sp.toString()}`)
}

export async function fetchHardwareStocktakeClient(id: string): Promise<HardwareStocktakeRecord> {
  return apiGet<HardwareStocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes/${id}`)
}

export async function createHardwareStocktakeClient(
  takeType: string, note?: string,
): Promise<HardwareStocktakeRecord> {
  return apiPost<HardwareStocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes`, {
    take_type: takeType,
    note,
  })
}

export async function fillHardwareStocktakeItemClient(
  takeId: string, itemId: string, actualQty: number, explanation?: string,
): Promise<HardwareStocktakeItemRecord> {
  return apiPut<HardwareStocktakeItemRecord>(
    `${CLIENT_API}${BASE}/stocktakes/${takeId}/items/${itemId}`,
    { actual_qty: actualQty, explanation },
  )
}

export async function reviewHardwareStocktakeClient(
  takeId: string, explainedBy: string, note?: string,
): Promise<HardwareStocktakeRecord> {
  return apiPost<HardwareStocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes/${takeId}/review`, {
    explained_by: explainedBy,
    note,
  })
}

export async function confirmHardwareStocktakeClient(
  takeId: string, confirmedBy: string,
): Promise<HardwareStocktakeRecord> {
  return apiPost<HardwareStocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes/${takeId}/confirm`, {
    confirmed_by: confirmedBy,
  })
}

export async function cancelHardwareStocktakeClient(id: string): Promise<HardwareStocktakeRecord> {
  return apiPost<HardwareStocktakeRecord>(`${CLIENT_API}${BASE}/stocktakes/${id}/cancel`, {})
}

export function hardwareStocktakeExportUrl(takeId: string): string {
  return `${CLIENT_API}${BASE}/stocktakes/${takeId}/export`
}

// ── 退库（二期 M4）──

export async function fetchHardwareReturnsClient(
  params: { status?: string; dept_name?: string; page?: number; pageSize?: number } = {},
): Promise<PaginatedCompat<HardwareReturnRecord>> {
  const sp = new URLSearchParams()
  if (params.status) sp.set('status', params.status)
  if (params.dept_name) sp.set('dept_name', params.dept_name)
  sp.set('page', String(params.page ?? 1))
  sp.set('page_size', String(params.pageSize ?? 20))
  return apiFetchPaginated<HardwareReturnRecord>(`${CLIENT_API}${BASE}/returns?${sp.toString()}`)
}

export interface HardwareReturnCreateInput {
  dept_name: string
  returned_by: string
  remark?: string
  items: Array<{
    material_id: string
    quantity: number
    preferred_lot_id?: string
  }>
}

export async function createHardwareReturnClient(
  payload: HardwareReturnCreateInput,
): Promise<HardwareReturnRecord> {
  return apiPost<HardwareReturnRecord>(`${CLIENT_API}${BASE}/returns`, payload)
}

export async function signHardwareReturnClient(
  id: string, leader: string,
): Promise<HardwareReturnRecord> {
  return apiPost<HardwareReturnRecord>(`${CLIENT_API}${BASE}/returns/${id}/sign`, { leader })
}

export async function acceptHardwareReturnClient(
  id: string, acceptedBy: string,
): Promise<HardwareReturnRecord> {
  return apiPost<HardwareReturnRecord>(`${CLIENT_API}${BASE}/returns/${id}/accept`, {
    accepted_by: acceptedBy,
  })
}

export async function rejectHardwareReturnClient(
  id: string, reason: string,
): Promise<HardwareReturnRecord> {
  return apiPost<HardwareReturnRecord>(`${CLIENT_API}${BASE}/returns/${id}/reject`, { reason })
}


// ── 月度采购计划（二期 M5）──

export async function fetchHardwarePlansClient(
  page = 1, pageSize = 20,
): Promise<PaginatedCompat<HardwarePlanRecord>> {
  const sp = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return apiFetchPaginated<HardwarePlanRecord>(`${CLIENT_API}${BASE}/plans?${sp.toString()}`)
}

export async function fetchHardwarePlanClient(planMonth: string): Promise<HardwarePlanRecord> {
  return apiGet<HardwarePlanRecord>(`${CLIENT_API}${BASE}/plans/${planMonth}`)
}

export async function generateHardwarePlanClient(
  planMonth?: string, annotate = true,
): Promise<HardwarePlanRecord> {
  return apiPost<HardwarePlanRecord>(`${CLIENT_API}${BASE}/plans/generate`, {
    plan_month: planMonth, annotate,
  })
}

export async function updateHardwarePlanItemClient(
  planMonth: string, itemId: string,
  payload: { purchase_qty?: number; remark?: string; ai_note?: string },
): Promise<HardwarePlanItemRecord> {
  return apiPut<HardwarePlanItemRecord>(
    `${CLIENT_API}${BASE}/plans/${planMonth}/items/${itemId}`, payload,
  )
}

export function hardwarePlanExportUrl(planMonth: string): string {
  return `${CLIENT_API}${BASE}/plans/${planMonth}/export`
}

// ── 温湿度日检（二期 M5）──

export async function upsertHardwareEnvLogClient(
  payload: {
    log_date: string
    temperature?: number
    humidity?: number
    checked_by?: string
    abnormal_note?: string
  },
): Promise<HardwareEnvLogRecord> {
  return apiPost<HardwareEnvLogRecord>(`${CLIENT_API}${BASE}/env-logs`, payload)
}

export async function fetchHardwareEnvLogsClient(days = 30): Promise<HardwareEnvLogRecord[]> {
  const data = await apiGet<HardwareEnvLogRecord[]>(
    `${CLIENT_API}${BASE}/env-logs?days=${days}`,
  )
  return data ?? []
}


// ── 报表完善（二期 M6）──

export function hardwareMovementsExportUrl(params: {
  direction?: string
  business_type?: string
  keyword?: string
  dept_name?: string
  erp_status?: string
} = {}): string {
  const sp = new URLSearchParams()
  if (params.direction) sp.set('direction', params.direction)
  if (params.business_type) sp.set('business_type', params.business_type)
  if (params.keyword) sp.set('keyword', params.keyword)
  if (params.dept_name) sp.set('dept_name', params.dept_name)
  if (params.erp_status) sp.set('erp_status', params.erp_status)
  const qs = sp.toString()
  return `${CLIENT_API}${BASE}/movements/export${qs ? `?${qs}` : ''}`
}
