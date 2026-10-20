/**
 * 特种设备遥测监控数据层（facilities-p2）。
 *
 * 票 01：latest（实时读数）/ history（趋势序列）；报警与待补录接口随票 02/04 补齐。
 */
import { apiGet, apiPost, API_BASE_URL } from '@/lib/http-client'
import type {
  Paged,
  TelemetryAlarm,
  TelemetryHistoryData,
  TelemetryLatestData,
  TelemetryPendingReview,
  TelemetryRuleItem,
} from '@/types/safety/telemetry'

export async function fetchTelemetryLatest(equipmentNo?: string): Promise<TelemetryLatestData> {
  const qs = equipmentNo ? `?equipment_no=${encodeURIComponent(equipmentNo)}` : ''
  return apiGet(API_BASE_URL + '/api/v1/safety/telemetry/latest' + qs)
}

export async function fetchTelemetryHistory(params: {
  equipment_no: string
  metric: string
  interval: 'hour' | 'day'
  from?: string
  to?: string
}): Promise<TelemetryHistoryData> {
  const sp = new URLSearchParams()
  sp.set('equipment_no', params.equipment_no)
  sp.set('metric', params.metric)
  sp.set('interval', params.interval)
  if (params.from) sp.set('from', params.from)
  if (params.to) sp.set('to', params.to)
  return apiGet(API_BASE_URL + '/api/v1/safety/telemetry/history?' + sp.toString())
}

export async function fetchTelemetryRules(): Promise<{ items: TelemetryRuleItem[] }> {
  return apiGet(API_BASE_URL + '/api/v1/safety/telemetry/rules')
}

export async function fetchTelemetryAlarms(params?: {
  status?: TelemetryAlarm['status']
  equipment_no?: string
  page?: number
  page_size?: number
}): Promise<Paged<TelemetryAlarm>> {
  const sp = new URLSearchParams()
  if (params?.status) sp.set('status', params.status)
  if (params?.equipment_no) sp.set('equipment_no', params.equipment_no)
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiGet(API_BASE_URL + '/api/v1/safety/telemetry/alarms' + (qs ? '?' + qs : ''))
}

/** 值班确认（firing → acked） */
export async function ackTelemetryAlarm(id: string) {
  return apiPost(API_BASE_URL + `/api/v1/safety/telemetry/alarms/${id}/ack`, {})
}

/** 处置关闭（acked → resolved；说明必填） */
export async function resolveTelemetryAlarm(id: string, note: string) {
  return apiPost(API_BASE_URL + `/api/v1/safety/telemetry/alarms/${id}/resolve`, { note })
}

export async function fetchTelemetryPendingReviews(params?: {
  page?: number
  page_size?: number
}): Promise<Paged<TelemetryPendingReview>> {
  const sp = new URLSearchParams()
  if (params?.page) sp.set('page', String(params.page))
  if (params?.page_size) sp.set('page_size', String(params.page_size))
  const qs = sp.toString()
  return apiGet(API_BASE_URL + '/api/v1/safety/telemetry/pending-reviews' + (qs ? '?' + qs : ''))
}

/** 人工补录确认（pending 行转正 manual 快照） */
export async function confirmTelemetryPendingReview(
  id: string,
  body: { equipment_no: string; readings: Array<{ metric: string; value: number; unit?: string; recorded_at?: string }> },
) {
  return apiPost(API_BASE_URL + `/api/v1/safety/telemetry/pending-reviews/${id}/confirm`, body)
}
