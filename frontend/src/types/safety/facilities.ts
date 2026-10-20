/**
 * 安全设备设施管理（facilities-p1）类型。
 *
 * 三台账三态信封字段口径 = backend app/modules/safety/facilities/ledger.py
 * 标准字段；任务中心类型随票 03 补齐。
 */

export type FacilitiesStatus = 'not_connected' | 'live' | 'degraded'

/** 台账 url key（API 路径段） */
export type FacilitiesLedgerKey = 'accessories' | 'fire-equipment' | 'special-equipment'

export interface FacilitiesLedgerMeta {
  total: number
  page: number
  page_size: number
}

/** 台账标准字段行（日期为 ISO 字符串） */
export interface FacilitiesLedgerRow {
  record_id: string
  biz_type: string
  equipment_no: string | null
  name: string | null
  category: string | null
  location: string | null
  department: string | null
  owner: string | null
  last_date: string | null
  cycle_months: number | null
  next_date: string | null
  anchor: string | null
  anchor_source: 'next_date' | 'derived' | 'none'
  status: string | null
  refill_due: string | null
  scrap_due: string | null
  register_code: string | null
  inspection_category: string | null
  agency: string | null
  monitor_flag: boolean
  active: boolean
  remaining_days: number | null
  incomplete_reason: string | null
}

export interface FacilitiesLedgerSummary {
  biz_type: string
  biz_label: string
  total: number
  active: number
  overdue: number
  due_30d: number
  incomplete: number
}

export interface FacilitiesLedgerPageData {
  status: FacilitiesStatus
  summary: FacilitiesLedgerSummary | null
  ledger: { data: FacilitiesLedgerRow[]; meta: FacilitiesLedgerMeta }
  errors: string[]
}

// ── 校验任务中心（票 03）────────────────────────────────────────────

export interface FacilityTask {
  id: string
  biz_type: string
  biz_label: string
  ledger_key: string
  equipment_no: string | null
  equipment_name: string | null
  department: string | null
  location: string | null
  task_kind: string
  task_subtype: string
  group_key: string
  due_date: string
  lead_days: number
  status: 'issued' | 'closed' | 'cancelled'
  assignee_name: string | null
  batch_id: string | null
  anchor_at_dispatch: string
  issued_on: string
  closed_trigger: 'event' | 'poll' | 'manual' | null
  closed_reason: string | null
  closed_at: string | null
  remind_count: number
  remaining_days: number | null
  overdue: boolean
}

export interface FacilityTaskGroupBucket {
  group_key: string
  total: number
  closed: number
}

export interface FacilityTaskDepartmentBucket {
  department: string
  total: number
  closed: number
  open: number
  groups: FacilityTaskGroupBucket[]
}

export interface FacilityTaskSummary {
  total: number
  open: number
  closed: number
  cancelled: number
  overdue: number
  by_department: FacilityTaskDepartmentBucket[]
}

export interface FacilityTaskEvent {
  id: string
  task_id: string
  event_type: 'issued' | 'closed' | 'cancelled' | 'reminded' | 'escalated' | 'reopened'
  operator: string | null
  closed_trigger: 'event' | 'poll' | 'manual' | null
  payload: Record<string, unknown> | null
  created_at: string | null
}

export interface FacilityTaskDetail {
  task: FacilityTask
  events: FacilityTaskEvent[]
}
