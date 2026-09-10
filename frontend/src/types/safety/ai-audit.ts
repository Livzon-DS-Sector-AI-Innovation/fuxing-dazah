// AI 调用审计（safety.ai_call_audits）类型

export interface AiCallAuditListItem {
  id: string
  created_at: string
  trace_id: string | null
  scenario: string
  resource_type: string | null
  resource_id: string | null
  session_id: string | null
  channel: string | null
  user_name: string | null
  model: string
  prompt_version: string | null
  input_preview: string | null
  output_preview: string | null
  input_tokens: number | null
  output_tokens: number | null
  cache_hit_tokens: number | null
  cache_miss_tokens: number | null
  latency_ms: number | null
  status: string
  degradation_level: string | null
}

export interface AiCallAuditDetail extends AiCallAuditListItem {
  input_text: string | null
  input_truncated: boolean
  output_text: string | null
  output_truncated: boolean
  ip_address: string | null
  error: string | null
  cited_sources: { doc_title?: string; article_ref?: string }[] | null
  guard_hits: string[] | null
  extra: Record<string, unknown> | null
}

export interface AiAuditScenarioStats {
  scenario: string
  calls: number
  input_tokens: number
  output_tokens: number
  cache_hit_tokens: number
  cache_miss_tokens: number
  avg_latency_ms: number
  failed: number
}

export interface AiAuditDailyPoint {
  date: string
  scenario: string
  calls: number
  input_tokens: number
  output_tokens: number
  cache_hit_tokens: number
  cache_miss_tokens: number
  failed: number
}

export interface AiAuditTotals {
  calls: number
  input_tokens: number
  output_tokens: number
  cache_hit_tokens: number
  cache_miss_tokens: number
  failed: number
}

export interface AiAuditStats {
  days: number
  date_from: string
  date_to: string
  totals: AiAuditTotals
  prev_totals: AiAuditTotals
  by_scenario: AiAuditScenarioStats[]
  daily: AiAuditDailyPoint[]
}

export interface AiAuditQueryParams {
  scenario?: string
  status?: string
  channel?: string
  resource_id?: string
  user_name?: string
  keyword?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

// 场景值 → 中文标签（展示用）
export const AI_AUDIT_SCENARIO_LABELS: Record<string, string> = {
  hazard_identification: '隐患识别',
  hazard_id_bitable: '危险源辨识',
  rectification_review: '整改初审',
  agent_chat: '助手对话',
  knowledge_chat: '知识库问答',
  graph_build: '图谱构建',
  regulation_crawl: '法规筛选',
  drill_plan_generation: '演练预案生成',
  drill_report_generation: '演练报告生成', // 已废弃，保留兼容
  daily_report_analysis: '日报AI分析',
  drill_issue_parsing: '演练问题解析',
  drill_plan_parsing: '演练计划解析',
  drill_eval_parsing: '演练评估解析',
  embedding: '向量嵌入',
  rerank: '相关性重排',
  memory_extraction: '记忆提取',
  ehs_change_review: 'EHS变更审核',
  contractor_admission_review: '相关方准入审核',
  msds_extraction: 'MSDS提取',
  sop_generation: '操规AI补全',
  sop_review: '操规AI审核',
  regulation_ocr: '法规扫描件OCR',
  oh_transfer_hazard_diff: '转岗危害差异',
  oh_exam_report_parsing: '体检AI解析',
  fire_alarm_analysis: '消防报警分析',
  central_alarm_analysis: '中控报警分析',
  unknown: '未归因',
}
