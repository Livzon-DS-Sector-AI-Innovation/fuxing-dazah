// 智能中心 API（分期B）：读走 client 相对路径，写走 Server Actions 引用的服务端函数
import {
  AlertRecordItem,
  AlertSummary,
  IntelligenceRule,
  Paginated,
  ReplenishmentSuggestionItem,
} from '@/types/warehouse'
import { apiGet, apiFetchPaginated, apiPost, apiPut } from '@/lib/http-client'

const SERVER_API = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const CLIENT_API = process.env.NEXT_PUBLIC_API_BASE_URL || ''
const BASE = '/api/v1/warehouse/intelligence'
const REPLENISHMENT_BASE = '/api/v1/warehouse/replenishment'

// ── 读（client） ──

export async function fetchIntelligenceRulesClient(): Promise<IntelligenceRule[]> {
  return apiGet<IntelligenceRule[]>(`${CLIENT_API}${BASE}/rules`)
}

export async function fetchAlertsClient(
  params: { rule_key?: string; status?: string; page?: number; page_size?: number } = {},
): Promise<Paginated<AlertRecordItem>> {
  const sp = new URLSearchParams()
  if (params.rule_key) sp.set('rule_key', params.rule_key)
  if (params.status) sp.set('status', params.status)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiFetchPaginated<AlertRecordItem>(`${CLIENT_API}${BASE}/alerts${qs ? `?${qs}` : ''}`)
}

export async function fetchAlertSummaryClient(ruleKey: string): Promise<AlertSummary> {
  return apiGet<AlertSummary>(
    `${CLIENT_API}${BASE}/alerts/summary?rule_key=${encodeURIComponent(ruleKey)}`,
  )
}

export async function fetchSuggestionsClient(
  params: { status?: string; page?: number; page_size?: number } = {},
): Promise<Paginated<ReplenishmentSuggestionItem>> {
  const sp = new URLSearchParams()
  if (params.status) sp.set('status', params.status)
  if (params.page) sp.set('page', String(params.page))
  if (params.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  const base = '/api/v1/warehouse/replenishment'
  return apiFetchPaginated<ReplenishmentSuggestionItem>(
    `${CLIENT_API}${base}/suggestions${qs ? `?${qs}` : ''}`,
  )
}

// ── 写（server，供 Server Actions 调用） ──

export async function updateIntelligenceRule(
  ruleKey: string,
  payload: { threshold?: Record<string, number>; enabled?: boolean },
): Promise<IntelligenceRule> {
  return apiPut<IntelligenceRule>(
    `${SERVER_API}${BASE}/rules/${encodeURIComponent(ruleKey)}`,
    payload,
  )
}

export async function resolveAlertRecord(recordId: string): Promise<AlertRecordItem> {
  return apiPost<AlertRecordItem>(
    `${SERVER_API}${BASE}/alerts/${encodeURIComponent(recordId)}/resolve`,
    {},
  )
}

export async function runIntelligenceScan(): Promise<{ counts: Record<string, number> }> {
  return apiPost<{ counts: Record<string, number> }>(`${SERVER_API}${BASE}/intelligence/scan`, {})
}

export async function setSuggestionStatus(
  suggestionId: string,
  status: 'handled' | 'ignored',
): Promise<ReplenishmentSuggestionItem> {
  return apiPost<ReplenishmentSuggestionItem>(
    `${SERVER_API}${REPLENISHMENT_BASE}/suggestions/${encodeURIComponent(suggestionId)}/status`,
    { status },
  )
}

// ── 库存分析定档（2026-11-04 直读改造）──

export interface AnalysisKpi {
  total_quantity: number
  stock_rows: number
  stock_skus: number
  material_count: number
  zero_stock_count: number
  frozen_count: number
  quarantine_count: number
}

export interface AnalysisAlerts {
  low_stock_count: number
  idle_count: number
  idle: Array<{
    material_code: string
    material_name: string
    total_quantity: number
    days_idle: number
    last_inbound_at: string | null
  }>
  expiry_count: number
  expiry: Array<{
    material_code: string
    material_name: string
    batch_no: string
    expiry_date: string
    days_left: number
  }>
}

export interface AnalysisSummary {
  kpi: AnalysisKpi
  distribution: Array<{ category: string; total_quantity: number }>
  top: {
    turnover: Array<{
      material_code: string
      material_name: string
      outbound_qty: number
      current_stock: number
      turnover: number | null
    }>
    consumption: Array<{
      material_code: string
      material_name: string
      unit: string
      outbound_qty: number
    }>
  }
  alerts: AnalysisAlerts
}

export interface AnalysisReportItem {
  id: string
  report_date: string
  trigger: 'scheduled' | 'manual' | string
  duration_ms: number
  summary: AnalysisSummary
  created_at: string | null
}

export async function fetchAnalysisLatestClient(): Promise<AnalysisReportItem | null> {
  const data = await apiGet<AnalysisReportItem | null>(
    `${CLIENT_API}/api/v1/warehouse/analysis/latest`,
  )
  return data
}

export async function fetchAnalysisReportsClient(
  page = 1,
  pageSize = 20,
): Promise<{ items: AnalysisReportItem[]; total: number }> {
  return apiFetchPaginated<AnalysisReportItem>(
    `${CLIENT_API}/api/v1/warehouse/analysis/reports?page=${page}&page_size=${pageSize}`,
  )
}

export async function runAnalysisClient(): Promise<AnalysisReportItem> {
  // 冷缓存首跑需全量拉生产台账（~70s）——3 分钟超时兜底
  return apiPost<AnalysisReportItem>(
    `${CLIENT_API}/api/v1/warehouse/analysis/run`,
    {},
    { signal: AbortSignal.timeout(180_000) },
  )
}
