/** 法规采集监控（契约③聚合 + 本仓收录留痕，三态信封） */

/** 监控三态：not_connected=未对接 | live=正常 | degraded=降级 */
export type RegulationMonitorStatus = 'not_connected' | 'live' | 'degraded'

/** 数据源健康行（ragplus 契约③透传） */
export interface RegulationCrawlSource {
  name: string
  layer?: string
  last_success_at?: string | null
  consecutive_failures?: number
  items_7d?: number
  status?: 'ok' | 'warn' | 'down' | 'suspect_rebuild' | string
}

/** 最新收录卡片流条目 */
export interface RegulationFeedItem {
  candidate_id: string | null
  title: string | null
  url: string | null
  reason: string | null
  is_revision: boolean
  bitable_record_id: string | null
  ingested_at: string | null
}

/** 判定漏斗（左半 ragplus 留痕 / 右半本仓留痕） */
export interface RegulationAiFunnel {
  discovered: number | null
  parsed: number | null
  received: number
  deduped: number
  ai_judged: number
  promoted: number
  rejected: number
  window_days: number
}

/** StatCard 六卡口径 */
export interface RegulationMonitorStats {
  sources_total: number
  sources_healthy: number
  items_7d: number
  ai_relevant_7d: number
  pending_review: number
  attachment_missing: number
  last_run_at: string | null
  last_run_status: string | null
  last_run_source_id: string | null
  ragplus_last_run_at: string | null
  ragplus_last_run_status: string | null
}

/** 本仓收录留痕行（运行历史表） */
export interface RegulationIngestRunRow {
  run_log_id: string
  source_run_id: string
  source: string
  status: string
  received_count: number
  duplicate_count: number
  pending_count: number
  promoted_count: number
  rejected_count: number
  failed_count: number
  ai_tokens_used: number
  items_result: Array<{
    candidate_id: string
    action_taken: string
    reason: string
    bitable_record_id?: string | null
    title?: string | null
    url?: string | null
    attachment_missing?: boolean
  }>
  receipts: Record<string, { action: string; ok: boolean; error?: string }> | null
  error_summary: string | null
  created_at: string | null
  finished_at: string | null
}

/** 监控聚合信封（GET /api/v1/safety/regulation-monitor） */
export interface RegulationMonitorData {
  status: RegulationMonitorStatus
  stats: RegulationMonitorStats
  sources: RegulationCrawlSource[]
  feed: RegulationFeedItem[]
  funnel: RegulationAiFunnel
  runs: {
    data: RegulationIngestRunRow[]
    meta: { total: number; page: number; page_size: number }
  }
  errors: string[]
}

/** 运行详情（GET .../runs/{run_id}，两段拼接） */
export interface RegulationRunDetail {
  ingest: RegulationIngestRunRow
  ragplus_run: Record<string, unknown> | null
  errors: string[]
}
