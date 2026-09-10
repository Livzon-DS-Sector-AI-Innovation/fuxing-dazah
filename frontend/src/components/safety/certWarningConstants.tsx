// 人员培训及持证资质智能管理（Cert Warning）— UI 常量 & 视觉映射
// 配色取自 DESIGN.md tokens / shared-styles，结构对标 ohConstants.tsx
// 后端权威清单：`dazah-backend/app/modules/safety/schemas/cert_warnings.py`
//   6 档预警等级 WarningLevel + 3 类证件 CertCategory

import { T } from './shared-styles'
import { UI, CARD_STYLE } from './emergencyDrillConstants'

export { T, UI, CARD_STYLE }

// ── 预警等级（6 档） → 视觉 ──

export const WARNING_LEVEL_UI: Record<string, { label: string; color: string; bg: string }> = {
  normal: { label: '正常', color: T.success, bg: T.mint },
  early_notice: { label: '提前关注', color: '#0075de', bg: T.sky },
  to_schedule: { label: '待安排', color: T.warning, bg: T.yellow },
  key_warning: { label: '重点预警', color: '#793400', bg: T.peach },
  urgent: { label: '紧急预警', color: T.error, bg: T.rose },
  overdue: { label: '已逾期', color: T.error, bg: T.rose },
}

export const WARNING_LEVEL_FILTER = [
  { value: '', label: '全部状态' },
  { value: 'normal', label: '正常' },
  { value: 'early_notice', label: '提前关注' },
  { value: 'to_schedule', label: '待安排' },
  { value: 'key_warning', label: '重点预警' },
  { value: 'urgent', label: '紧急预警' },
  { value: 'overdue', label: '已逾期' },
]

// ── 证件类别（3 类） → 视觉 ──

export const CERT_CATEGORY_UI: Record<string, { label: string; color: string; bg: string }> = {
  special_op: { label: '特种作业证', color: '#0075de', bg: T.sky },
  guardian_a: { label: '监护人A证', color: T.primary, bg: T.lavender },
  guardian_b: { label: '监护人B证', color: T.warning, bg: T.peach },
}

export const CERT_CATEGORY_FILTER = [
  { value: '', label: '全部类型' },
  { value: 'special_op', label: '特种作业证' },
  { value: 'guardian_a', label: '监护人A证' },
  { value: 'guardian_b', label: '监护人B证' },
]

// ── 顶部 KPI 卡片定义（label → summary 字段）──

export const WARNING_KPI_ITEMS: Array<{
  label: string
  field: keyof import('@/types/safety').CertWarningSummary
  bg: string
  valueColor: string
  caption: string
}> = [
  { label: '已逾期', field: 'overdue_count', bg: T.rose, valueColor: T.error, caption: '<0 天' },
  { label: '紧急预警', field: 'urgent_count', bg: T.rose, valueColor: T.error, caption: '0-7 天' },
  { label: '重点预警', field: 'key_warning_count', bg: T.peach, valueColor: T.warning, caption: '8-30 天' },
  { label: '待安排', field: 'to_schedule_count', bg: T.yellow, valueColor: '#793400', caption: '31-60 天' },
  { label: '提前关注', field: 'early_notice_count', bg: T.sky, valueColor: '#005bab', caption: '61-90 天' },
  { label: '总数', field: 'total', bg: T.lavender, valueColor: T.primary, caption: '全部持证' },
]