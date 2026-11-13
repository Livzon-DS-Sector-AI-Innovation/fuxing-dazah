// R3 运维自愈观测 —— 类型定义（对齐后端 api/ops_selfheal.py 序列化结构）

/** R3 工单列表行（_serialize_ticket） */
export interface OpsSelfhealTicket {
  id: string
  short_name: string
  title: string
  stage: string
  stage_label: string
  status: string
  outcome: string | null
  signal: string | null
  job_name: string | null
  component: string | null
  root_cause_class: string | null
  confidence: number | null
  diag_source: string | null
  reasoning: string | null
  executed: string[]
  planned: string[]
  repair_rounds: number | null
  dep_endpoints: string[]
  missed_days: string[] | null
  backfill_summary: string | null
  escalate_guidance: string | null
  first_seen_at: string | null
  diag_at: string | null
  mandate_rule: string | null
  created_at: string | null
  updated_at: string | null
  ended_at: string | null
}

/** 工单列表响应（分页 meta） */
export interface OpsSelfhealTicketList {
  data: OpsSelfhealTicket[]
  meta: { page: number; page_size: number; total: number }
}

/** 时间线事件（trigger→decision→input→effect→outbox 五段） */
export interface OpsSelfhealTimelineEvent {
  kind: 'trigger' | 'decision' | 'input' | 'effect' | 'outbox'
  at: string | null
  external_id?: string
  thread_key?: string
  signal?: string
  disposition?: string[]
  payload?: Record<string, unknown>
  rule_id?: string
  outcome?: string
  would_accept?: boolean
  mode?: string
  resolution?: string | null
  resolved_by?: string
  input_kind?: string
  read_at?: string | null
  effect_kind?: string
  action?: string | null
  dedupe_key?: string
  status?: string
  attempts?: number
  last_error?: string | null
  purpose?: string
  seq?: number
}

/** 时间线响应 */
export interface OpsSelfhealTimeline {
  ticket: OpsSelfhealTicket
  events: OpsSelfhealTimelineEvent[]
  event_count: number
}

/** 一键执行窗口延长响应 */
export interface ExtendWindowResult {
  id: string
  job_name: string
  old_window: string
  new_window: string
}
