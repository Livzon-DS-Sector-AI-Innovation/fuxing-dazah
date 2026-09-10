// URS 智能审核 常量与语义色映射（DESIGN tokens）
import type { CSSProperties } from 'react'
import { statusPill, T } from '../shared-styles'

// ── 审核状态 → 语义色 pill ──
export const URS_STATUS_UI: Record<string, { label: string; pill: CSSProperties }> = {
  draft: { label: '草稿', pill: statusPill('#a4a097', '#f0eeec') },
  pending_assessment: { label: '待评估', pill: statusPill('#787671', '#f0eeec') },
  assessing: { label: '评估中', pill: statusPill('#0075de', '#dcecfa') },
  failed: { label: '评估失败', pill: statusPill('#e03131', '#fde0ec') },
  assessment_confirmed: { label: '评估已确认', pill: statusPill('#1aae39', '#d9f3e1') },
  human_review: { label: '待人工复核', pill: statusPill('#dd5b00', '#ffe8d4') },
  adapting: { label: '标准适配中', pill: statusPill('#0075de', '#dcecfa') },
  item_review: { label: '逐条审核', pill: statusPill('#5645d4', '#e6e0f5') },
  conclusion: { label: '结论生成中', pill: statusPill('#0075de', '#dcecfa') },
  approved: { label: '已通过', pill: statusPill('#1aae39', '#d9f3e1') },
  rejected: { label: '已驳回', pill: statusPill('#e03131', '#fde0ec') },
  appeal: { label: '申诉中', pill: statusPill('#5645d4', '#e6e0f5') },
  closed: { label: '已闭环', pill: statusPill('#787671', '#f0eeec') },
}

export const URS_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(URS_STATUS_UI).map(([value, v]) => ({ value, label: v.label })),
]

// ── 风险等级 → 色块（高红/中橙/低绿）──
export const RISK_LEVEL_UI: Record<string, { label: string; pill: CSSProperties }> = {
  high: { label: '高风险', pill: statusPill(T.error, '#fde0ec') },
  medium: { label: '中风险', pill: statusPill(T.warning, '#ffe8d4') },
  low: { label: '低风险', pill: statusPill(T.success, '#d9f3e1') },
}

// ── 标准适配等级 → 色块 ──
export const APPLICABILITY_UI: Record<string, { label: string; pill: CSSProperties }> = {
  mandatory: { label: '强制', pill: statusPill('#e03131', '#fde0ec') },
  recommended: { label: '建议', pill: statusPill('#dd5b00', '#ffe8d4') },
  not_applicable: { label: '不适用', pill: statusPill('#a4a097', '#f0eeec') },
}

// ── 逐条审核结论 → 色块 ──
export const ITEM_VERDICT_UI: Record<string, { label: string; pill: CSSProperties }> = {
  pending: { label: '待审核', pill: statusPill('#a4a097', '#f0eeec') },
  passed: { label: '通过', pill: statusPill('#1aae39', '#d9f3e1') },
  failed: { label: '不通过', pill: statusPill('#e03131', '#fde0ec') },
  skipped: { label: '跳过', pill: statusPill('#a4a097', '#f0eeec') },
}

// ── 五维风险维度标签 ──
export const RISK_DIMENSION_LABELS: Record<string, string> = {
  mechanical: '机械',
  electrical: '电气',
  data: '数据',
  environmental: '环境',
  chemical: '化学',
  none: '通用', // seed 中 S6.x 职业健康通用条款 risk_dimension='none'
}

export const RISK_DIMENSION_KEYS = ['mechanical', 'electrical', 'data', 'environmental', 'chemical']

// ── 标准条款类别标签（与后端 ai_urs_review/seed_items.py 的 CATEGORY_LABELS 对齐）──
export const CATEGORY_LABELS: Record<string, string> = {
  data_integrity: 'GMP数据完整性',
  motion_guard: '运动部件防护（否决项）',
  fire_explosion: '防火防爆',
  environmental: '废水废气处理',
  mechanical_safety: '机械安全',
  electrical_safety: '电气安全',
  data_system: '数据系统',
  chemical_safety: '化学品安全',
  env_health: '环境与职业健康',
  safety_distance: '安全距离与通道',
  loto: '能源隔离LOTO',
  noise: '噪声控制',
}
