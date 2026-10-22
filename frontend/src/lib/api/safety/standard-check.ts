/**
 * 体系标准核查数据层（S1 目标责任与绩效，2026-10-21 改造）。
 *
 * 三态信封（后端 service/standard_check/page.py）：
 * - not_connected 未接入：核查表未建/未登记（registry 连接位空）；
 * - live 已接入：summary 四态计数 + 八要素分组清单；
 * - degraded 降级：读取失败（errors 标注）。
 * 行四态 status：ok 达标 / in_progress 进行中 / missed 未达标 / no_data 无数据。
 * DESIGN：docs/DESIGN-安全目标责任与绩效模块-体系标准符合性核查引擎-20261021.md
 */
import { apiGet, API_BASE_URL } from '@/lib/http-client'

export type StandardCheckStatus = 'not_connected' | 'live' | 'degraded'

export type StandardRowStatus = 'ok' | 'in_progress' | 'missed' | 'no_data'

export interface StandardSummary {
  total: number
  ok: number
  in_progress: number
  missed: number
  no_data: number
  compliance_rate: number | null
}

export interface StandardRow {
  record_id: string
  no: string
  clause: string
  basis: string | null
  element: string | null
  metric_key: string | null
  period: string | null
  target_display: string
  department: string[]
  owner: string | null
  auto: boolean
  status: StandardRowStatus
  actual_display: string | null
  residual_days: number | null
  note: string | null
}

export interface StandardGroup {
  element: string
  rows: StandardRow[]
}

export interface StandardDeptSummary {
  name: string
  total: number
  ok: number
  in_progress: number
  missed: number
  no_data: number
}

export interface StandardCheckData {
  status: StandardCheckStatus
  summary: StandardSummary | null
  groups: StandardGroup[]
  departments: StandardDeptSummary[]
  errors: string[]
}

export interface StandardCheckFilters {
  year?: number
  element?: string
  status?: StandardRowStatus
  department?: string
}

export async function fetchStandardCheckPage(
  filters?: StandardCheckFilters,
): Promise<StandardCheckData> {
  const sp = new URLSearchParams()
  if (filters?.year) sp.set('year', String(filters.year))
  if (filters?.element) sp.set('element', filters.element)
  if (filters?.status) sp.set('status', filters.status)
  if (filters?.department) sp.set('department', filters.department)
  const qs = sp.toString()
  return apiGet(
    API_BASE_URL + '/api/v1/safety/goals/standards' + (qs ? '?' + qs : ''),
  )
}

export interface StandardEvidenceItem {
  title: string
  date: string
  type: string
  url?: string | null
}

export interface StandardEvidenceData {
  status: 'live' | 'not_connected' | 'degraded' | 'not_found'
  record_id?: string
  no?: string
  clause?: string
  metric_key?: string | null
  window?: { start: string; end: string }
  verdict_status?: StandardRowStatus
  actual_display?: string | null
  evidence: StandardEvidenceItem[]
  no_data_reason: string | null
}

export async function fetchStandardEvidence(
  recordId: string,
): Promise<StandardEvidenceData> {
  return apiGet(
    API_BASE_URL + `/api/v1/safety/goals/standards/evidence?record_id=${encodeURIComponent(recordId)}`,
  )
}
