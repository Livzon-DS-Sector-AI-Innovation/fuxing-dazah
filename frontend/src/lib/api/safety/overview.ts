import { apiGet, API_BASE_URL } from '@/lib/http-client'

/** 总览驾驶舱聚合数据（GET /safety/overview 一次拉取，3.0 只读口径） */

export interface OverviewHazards {
  unclosed: number
  delta: number
  overdue: number
  trend: { dates: string[]; created: number[]; closed: number[] }
}

export interface OverviewSpecialOps {
  today_total: number
  high: number
}

export interface OverviewAlarms {
  today_total: number
  fire_today: number
  central_today: number
  fire_real_today: number
  analysis: {
    dates: string[]
    fire_daily: number[]
    central_daily: number[]
    top_fire_types: { name: string; count: number }[]
  }
}

export interface OverviewCerts {
  within_30d: number
  urgent_or_overdue: number
  items: {
    person_name: string
    department: string | null
    cert_category: string
    deadline: string | null
    remaining_days: number | null
  }[]
}

export interface OverviewChemicals {
  over_limit: number
  materials: {
    material_name: string
    department: string | null
    storage_location: string | null
    total_quantity_t: number
    max_limit: number
    unit: string | null
  }[]
}

export interface OverviewKeyRiskOps {
  today_approved: number
  in_progress: number
  items: {
    start_time: string | null
    department: string | null
    operation_content: string | null
    apply_status: string | null
  }[]
}

export interface OverviewDigestCell {
  key: string
  tag_color: string
  tag_text: string
  title: string
  stats: string
  zone: string
  detail: string
  sent_at: string | null
}

export interface OverviewDigest {
  count: number
  cells: OverviewDigestCell[]
}

/** ok=正常 / warn=预警 / inactive=未开展（灰，可点占位页）/ upcoming=未上线（灰，不可点） */
export type ModuleHealthStatus = 'ok' | 'warn' | 'inactive' | 'upcoming'

export interface OverviewModuleHealth {
  key: string
  status: ModuleHealthStatus
  metric: string | null
}

export interface SafetyOverview {
  date: string
  generated_at: string
  hazards: OverviewHazards | null
  special_ops: OverviewSpecialOps | null
  alarms: OverviewAlarms | null
  certs: OverviewCerts | null
  chemicals: OverviewChemicals | null
  key_risk_ops: OverviewKeyRiskOps | null
  digest: OverviewDigest | null
  module_health: OverviewModuleHealth[]
  errors: string[]
}

export async function fetchSafetyOverview(): Promise<SafetyOverview> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/overview`)
}
