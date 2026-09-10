// ============ 中控报警分析（central-alarm-analysis）Types ============
// 契约对齐：ticket 03（records/stats，分布为 dict）、ticket 05/06（日常报告 report_kind/analyzed）

/** AI 异常模式（英文枚举，后端归一化后回写；前端经 AI_PATTERN_CONFIG 映射中文） */
export type CentralAlarmPattern =
  | 'normal_transient'
  | 'repeated'
  | 'false_alarm'
  | 'anomalous'

/** AI 分析维度（英文枚举，后端归一化后回写） */
export type CentralAlarmDimension = 'process' | 'operation' | 'equipment' | 'other'

/** 报警记录（列表/详情共用，来源 safety.central_alarm_records） */
export interface CentralAlarmRecord {
  id: string
  feishu_record_id?: string | null
  source?: string | null
  alarm_date?: string | null // ISO 时间，前端 dayjs 格式化
  post?: string | null // 岗位（Bitable 单选）
  alarm_description?: string | null // 报警情况说明（自由文本）
  special_note?: string | null // 特殊情况说明
  workshop?: string | null // 车间（如 车间一）
  line?: string | null // 产线/区域（如 达托）
  // AI 分析字段组（日报生成时回写）
  ai_alarm_type?: string | null // 结构化报警类型（高液位/高温/误报等）
  ai_equipment?: string | null // AI 抽取设备
  ai_pattern?: string | null // 取值见 CentralAlarmPattern（未知值前端降级灰 Tag 原文显示）
  ai_dimension?: string | null
  ai_reason_analysis?: string | null
  ai_rectification_direction?: string | null
  ai_analyzed_at?: string | null
  synced_at?: string | null
  created_at?: string | null
}

/** 列表查询参数（日期 YYYY-MM-DD） */
export interface CentralAlarmQueryParams {
  page?: number
  page_size?: number
  date_from?: string
  date_to?: string
  workshop?: string
  line?: string
  post?: string
  ai_alarm_type?: string
  ai_dimension?: string
  ai_pattern?: string
  keyword?: string
}

/** KPI 统计（分布均为 dict[str, int]，统计口径默认本周） */
export interface CentralAlarmStats {
  date: string
  today_total: number
  week_total: number
  total_count: number
  week_ai_analyzed_count: number
  workshop_distribution: Record<string, number>
  post_distribution: Record<string, number>
  alarm_type_distribution: Record<string, number>
  pattern_distribution: Record<string, number>
  dimension_distribution: Record<string, number>
}

/** Bitable 多表全量同步结果 */
export interface CentralAlarmSyncResult {
  synced_count: number
  soft_deleted_count?: number
}

/** 日报生成请求（target_date 可选，默认当天·北京时区） */
export interface CentralAlarmDailyReportRequest {
  target_date?: string
}

/** 推送结果项 */
export interface CentralAlarmPushResult {
  chat_id: string
  success: boolean
  message_id?: string
  skipped?: boolean
  reason?: string
  error?: string
}

/** 日报生成响应（不落库，前端弹窗展示） */
export interface CentralAlarmReportResponse {
  report_kind: 'daily'
  target_date: string
  total: number
  analyzed: number
  markdown_report: string
  push_results: CentralAlarmPushResult[]
  records_analyzed?: string[]
}
