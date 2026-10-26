// 监护补贴统计 — 与后端 /subsidy/* 响应对齐（api/subsidy.py，DESIGN 20261026）

export interface SubsidySourceDept {
  department: string
  source: 'dept_ledger'
}

export interface SubsidyGuardianSummaryRow {
  guardian_name: string
  guardian_level: string
  hot_work: number
  height_work: number
  confined_space: number
  temporary_electricity: number
  blind_plate: number
  excavation: number
  road_breaking: number
  lifting: number
  total: number
}

export interface SubsidyDetailRow {
  guardian_name: string
  guardian_level: string
  ticket_no: string
  department: string
  operation_type: string
  operation_level: string
  location_content: string
  start_time: string
  end_time: string
  interval_hours: string
  raw_hours: number
  adjusted_hours: number
  billing_units: number
  billing_unit_label: string
  unit_price: number
  subsidy_amount: number
  remark: string
}

export interface SubsidyUnmatchedRow {
  name: string
  ticket_count: number
  operation_types: string[]
}

export interface SubsidySkippedRow {
  ticket_no: string
  ticket_type: string
  reason: string
}

export interface SubsidyStats {
  matched: number
  guardians: number
  /** 折算前合计（明细金额之和） */
  total_amount: number
  /** B 证 0.5 折算后实发合计（Excel K 列/月报口径） */
  adjusted_total: number
  unmatched: number
  unmatched_people: number
  skipped: number
}

export interface GuardianSubsidySummary {
  department: string
  year: number
  month: number
  source: string
  stats: SubsidyStats
  summaries: SubsidyGuardianSummaryRow[]
  details: SubsidyDetailRow[]
  unmatched: SubsidyUnmatchedRow[]
  skipped: SubsidySkippedRow[]
}
