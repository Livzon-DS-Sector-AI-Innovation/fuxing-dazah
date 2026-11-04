// 督办留痕（safety.hazard-audit）类型 —— 方向 C 展示层

export interface HazardAuditLastSubmission {
  text: string
  operator: string
  at: string | null
}

export interface HazardAuditItem {
  record_id: string
  hazard_no: string
  dunning_count: number
  dunning_recipient_count: number
  submission_count: number
  submission_failed: number
  last_submission: HazardAuditLastSubmission | null
  last_submission_at: string | null
  last_dunning_at: string | null
  last_activity_at: string | null
}

export type HazardAuditEventKind = 'submission' | 'dunning'

export interface HazardAuditEvent {
  kind: HazardAuditEventKind
  at: string | null
  outcome: string
  hazard_no: string
  /** submission */
  operator?: string
  text?: string
  /** dunning */
  role?: string
  name?: string
  receive_id?: string
}
