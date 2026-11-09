// 隐患 AI 识别质量看板（P1-4）— 与后端 quality_dashboard.build_quality_dashboard
// 返回结构一一对应；指标口径同源 quality_metrics（离线 replay 同款）。

/** 质量看板窗口元信息 */
export interface HazardQualityWindow {
  days: number
  from: string
  to: string
}

/** 总量与 JSON/闸门指标（P0-A 旧口径占位率在此段） */
export interface HazardQualityTotals {
  calls: number
  vision_calls: number
  text_calls: number
  json_valid_before: number
  json_valid_after: number
  repaired_recovered: number
  gate_pass_calls: number
  gate_fail_calls: number
  gate_unparseable_calls: number
  placeholder_calls: number
  degraded_calls: number
  json_valid_before_rate: number
  json_valid_after_rate: number
  gate_pass_rate: number
  placeholder_rate: number
}

/** 引用可验证性（C2/C3 口径；占位变体率分母=有证据调用） */
export interface HazardQualityCitation {
  calls_with_evidence: number
  calls_has_verified: number
  calls_zero_verified: number
  units_total: number
  units_verified: number
  placeholder_variant_calls: number
  call_verified_rate: number
  unit_verified_rate: number
  placeholder_variant_rate: number
}

/** 检索维度（P1-1 审计 extra 聚合；老审计行无字段不计分母） */
export interface HazardQualityRetrieval {
  calls_with_meta: number
  multi_query_calls: number
  rewrite_hit_calls: number
  avg_multi_query_count: number
  /** [文档名, 命中次数][]，至多 10 条 */
  top_docs: [string, number][]
}

/** 按日趋势（键为 YYYY-MM-DD） */
export interface HazardQualityDayStat {
  calls: number
  json_before: number
  json_after: number
  repaired: number
  gate_pass: number
  placeholder: number
  citation_ok: number
  placeholder_variant: number
}

/** 重跑窗口记录级闸门判定 */
export interface HazardQualityRerunRecords {
  records: number
  calls: number
  gate_pass_records: number
  gate_fail_records: number
}

/** P0-C 基线对照行（ok=null 表示窗口不同量不可比） */
export interface HazardQualityBaselineItem {
  metric: string
  baseline: number
  current: number
  floor: number | null
  ok: boolean | null
}

/** 死信条目（failure_ledger Redis 失败账本） */
export interface HazardDeadLetterItem {
  record_id: string
  attempts: number
  category: string
  reason: string
  last_round: number | null
  dead_at: number
}

/** 死信水位（count=null 表示账本读取失败、水位未知） */
export interface HazardDeadLetterWatermark {
  count: number | null
  items: HazardDeadLetterItem[]
}

/** GET /hazard-quality/dashboard 响应 data */
export interface HazardQualityDashboard {
  window: HazardQualityWindow
  totals: HazardQualityTotals
  citation: HazardQualityCitation
  retrieval: HazardQualityRetrieval
  gate_categories: Record<string, number>
  repair_stages: Record<string, number>
  by_day: Record<string, HazardQualityDayStat>
  rerun_records: HazardQualityRerunRecords
  baseline: HazardQualityBaselineItem[]
  dead_letters: HazardDeadLetterWatermark
}

// ── P1-3 例外复核 Tab（observe 口径）──────────────────────────────

/** 例外复核指标（exception_reviewer.summarize_exception_metrics 同构；
 *  P2-1 追加 auto 维度与 effective 口径键） */
export interface ExceptionReviewMetrics {
  exception_count: number
  analyzed_count: number
  exception_rate: number
  reviewed: number
  rescued: number
  rescued_rate: number
  /** P2-1 auto：写回成功 / 失败 / 待人工确认 / CAS 冲突 条数 */
  writeback_success: number
  writeback_failed: number
  pending_confirm: number
  cas_conflict: number
  /** 人工复核率 =（待确认+冲突+失败）/ 已复核（Q9A 口径） */
  manual_review_rate: number
  /** rescued 人工改判条数（human_feedback 非空） */
  human_override_count: number
  /** effective_rescued 率（人工>程序口径） */
  effective_rescued_rate: number
}

/** auto 升格达标提示（Q1C：近 14 天 effective 率≥60% 且样本≥10；只提示不强制） */
export interface ExceptionReviewAutoHint {
  eligible: boolean
  rescued_rate_14d: number
  samples_14d: number
}

/** 例外复核清单行 */
export interface ExceptionReviewItem {
  record_id: string
  source: string
  label: string
  rescued: boolean
  /** P2-1：人工>程序 的有效 rescued 口径 */
  effective_rescued: boolean
  action: string
  ai_basis: string
  observed_at: string
  note: string
  /** P2-1：写回状态 not_attempted/pending_confirm/success/failed/cas_conflict/gate_blocked */
  writeback: string
  /** 人工反馈：''/useful/useless */
  human_feedback: string
}

/** GET /hazard-quality/exception-reviews 响应 data（P1-3 observe + P2-1 auto 维度） */
export interface ExceptionReviewDashboard {
  window: HazardQualityWindow
  /** false = Redis 报告读取失败，指标按零降级展示 */
  reviews_available: boolean
  metrics: ExceptionReviewMetrics
  auto_hint: ExceptionReviewAutoHint
  dead_letters: HazardDeadLetterWatermark
  items: ExceptionReviewItem[]
}
