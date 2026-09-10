// ============ 消防报警分析（fire-alarm-analysis）Types ============
// 契约对齐：ticket 03（records/stats，分布为 dict）、ticket 07（报告 report_kind/analyzed）、
// ticket 08 实现要点（ai_dimension 为英文枚举 process/operation/equipment/other）

/** AI 二次分析维度（英文枚举，后端归一化后回写；前端经 AI_DIMENSION_CONFIG 映射中文） */
export type FireAlarmDimension = 'process' | 'operation' | 'equipment' | 'other'

/** 报警记录（列表/详情共用，来源 safety.fire_alarm_records） */
export interface FireAlarmRecord {
  id: string
  feishu_record_id?: string | null
  source?: string | null // bitable / manual（预留）
  alarm_time?: string | null // ISO 时间，前端 dayjs 格式化
  alarm_type?: string | null
  department?: string | null
  department_leader_name?: string | null
  building?: string | null
  location?: string | null // 报警部位
  alarm_nature?: string | null // 报警性质（误报/真实报警等，飞书自由文本）
  cause_category?: string | null // 原因分类
  cause_description?: string | null // 具体报警原因（人工填写，AI 二次理解对象）
  // AI 分析字段组（日报生成时回写）
  ai_dimension?: string | null // 取值见 FireAlarmDimension（未知值前端降级灰 Tag 原文显示）
  ai_reason_analysis?: string | null
  ai_rectification_direction?: string | null
  ai_analyzed_at?: string | null
  synced_at?: string | null
  created_at?: string | null
  // 不暴露 is_deleted：后端列表默认过滤软删除记录，前端不感知
}

/** 列表查询参数（日期 YYYY-MM-DD） */
export interface FireAlarmQueryParams {
  page?: number
  page_size?: number
  date_from?: string
  date_to?: string
  department?: string
  alarm_type?: string
  alarm_nature?: string
  ai_dimension?: string
  keyword?: string
}

/** KPI 统计（ticket 03 契约：分布均为 dict[str, int]，统计口径默认本周） */
export interface FireAlarmStats {
  date: string // 当日日期 ISO（target_date 或今天·北京时间）
  today_total: number // 今日报警数
  week_total: number // 本周（自然周 周一~周日·北京时间）报警数
  total_count: number // 全量报警数（非软删）
  week_ai_analyzed_count: number // 本周已 AI 分析的记录数
  nature_distribution: Record<string, number> // 报警性质 → 数量
  type_distribution: Record<string, number> // 报警类型 → 数量
  dimension_distribution: Record<string, number> // AI 维度 → 数量
  department_distribution: Record<string, number> // 部门 → 数量
}

/** Bitable 全量同步结果 */
export interface FireAlarmSyncResult {
  synced_count: number
  soft_deleted_count?: number
}

/** 日报生成请求（target_date 可选，默认当天·北京时区） */
export interface FireAlarmDailyReportRequest {
  target_date?: string
}

/** 周报生成请求（week_end 可选，默认本周日） */
export interface FireAlarmWeeklyReportRequest {
  week_end?: string
}

/** 推送结果项 */
export interface FireAlarmPushResult {
  chat_id: string
  success: boolean
  message_id?: string
  skipped?: boolean // 未配置推送目标时跳过
  reason?: string
  error?: string
}

/** 日报/周报生成响应（不落库，前端弹窗展示） */
export interface FireAlarmReportResponse {
  report_kind: 'daily' | 'weekly'
  target_date: string // 日报：当日；周报：周末日期
  week_start?: string | null // 周报：周一（日报为 null）
  total: number // 涉及记录数
  analyzed: number // 成功 AI 分析的记录数（降级时 < total）
  markdown_report: string
  push_results: FireAlarmPushResult[]
  records_analyzed?: string[] // 已 AI 回写的记录 id（仅日报）
}
