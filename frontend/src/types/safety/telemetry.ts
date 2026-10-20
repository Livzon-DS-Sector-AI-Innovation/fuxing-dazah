/**
 * 特种设备遥测监控类型（facilities-p2）。
 *
 * 后端 telemetry 域：latest=每设备每指标最新读数；history=按小时/日桶趋势
 * 序列；报警与待补录模型随票 02/04 补齐。
 */

export interface TelemetryLatestItem {
  equipment_no: string
  metric: string
  value: number
  unit: string | null
  recorded_at: string
  parse_method: string
  /** 单点最新值越界着色（normal/warning/alarm；报警判定另有连续点去抖口径） */
  status: 'normal' | 'warning' | 'alarm'
}

export interface TelemetryLatestData {
  items: TelemetryLatestItem[]
}

export interface TelemetryHistoryPoint {
  ts: string
  value: number
  count: number
}

export interface TelemetryHistoryData {
  equipment_no: string
  metric: string
  interval: 'hour' | 'day'
  points: TelemetryHistoryPoint[]
}

export type TelemetryParseMethod = 'template' | 'ai' | 'manual'

export type TelemetryAlarmStatus = 'firing' | 'acked' | 'resolved'

export interface TelemetryRuleItem {
  metric: string
  equipment_no?: string
  category?: string
  min?: number
  max?: number
  rate_per_min?: number
  consecutive: number
  level: 'warning' | 'alarm'
  unit?: string | null
  source: 'default' | 'override'
}

export interface TelemetryAlarm {
  id: string
  equipment_no: string
  metric: string
  value: number | null
  recorded_at: string
  rule_desc: string
  level: 'warning' | 'alarm'
  status: TelemetryAlarmStatus
  acked_at: string | null
  acked_by: string | null
  resolved_at: string | null
  resolution_note: string | null
  created_at: string
}

export interface TelemetryPendingReview {
  id: string
  equipment_no: string | null
  metric: string | null
  value: number | null
  unit: string | null
  recorded_at: string
  raw_message_id: string | null
  raw_excerpt: string | null
  parse_method: string
  created_at: string
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
