// 职业健康管理（Occupational Health）— UI 常量 & 视觉映射
// 后缀必须为 .tsx（design.md §七 铁律：含 icon/JSX 时必须 tsx，TS1005 踩坑）
// 配色取自 DESIGN.md tokens / shared-styles，结构对标 emergencyDrillConstants + msdsConstants
// 后端权威清单：`dazah-backend/app/modules/safety/service/oh_hazard_factor.py`
//   OH_HAZARD_FACTORS_STANDARD（42 项，与 Bitable 多选字段预设一致）

import { T } from './shared-styles'
import { UI, CARD_STYLE } from './emergencyDrillConstants'

export { T, UI, CARD_STYLE }

// ── 体检类型 → 视觉 ──

export const OH_EXAM_TYPE_UI: Record<string, { label: string; color: string; bg: string }> = {
  pre_employment: { label: '岗前', color: '#0075de', bg: T.sky },
  periodic: { label: '在岗期间', color: T.primary, bg: T.lavender },
  post_employment: { label: '离岗', color: T.steel, bg: T.gray },
  transfer: { label: '转岗', color: T.warning, bg: T.peach },
  emergency: { label: '应急', color: T.error, bg: T.rose },
}

export const OH_EXAM_TYPE_FILTER = [
  { value: '', label: '全部类型' },
  ...Object.entries(OH_EXAM_TYPE_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── AI 结论分类 → 视觉 ──

export const OH_AI_CONCLUSION_UI: Record<string, { label: string; color: string; bg: string }> = {
  normal: { label: '未见异常', color: T.success, bg: T.mint },
  abnormal_other: { label: '其他异常', color: T.warning, bg: T.peach },
  contraindicated: { label: '职业禁忌证', color: T.error, bg: T.rose },
  suspected_od: { label: '疑似职业病', color: T.error, bg: T.rose },
  od_diagnosed: { label: '职业病确诊', color: T.error, bg: T.rose },
  re_examination: { label: '复查', color: '#0075de', bg: T.sky },
}

/** 高危结论集合（行底色判定用；设计 §2.2） */
export const OH_HIGH_RISK_CONCLUSIONS = [
  'contraindicated',
  'suspected_od',
  'od_diagnosed',
]

/** 高危结论行底色（旧交互语义保留项，design §2.2；从常量导出避免组件内硬编码 hex） */
export const OH_HIGH_RISK_ROW_BG = '#fff2f0'

export const OH_AI_CONCLUSION_FILTER = [
  { value: '', label: '全部结论' },
  ...Object.entries(OH_AI_CONCLUSION_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── AI 解析状态 → 视觉 ──

export const OH_PARSE_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: '待解析', color: T.steel, bg: T.gray },
  parsing: { label: '解析中', color: '#0075de', bg: T.sky },
  parsed: { label: '已解析', color: T.success, bg: T.mint },
  failed: { label: '解析失败', color: T.error, bg: T.rose },
}

export const OH_PARSE_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(OH_PARSE_STATUS_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 岗位适配判定 → 视觉 ──

export const OH_FITNESS_UI: Record<string, { label: string; color: string; bg: string }> = {
  fit: { label: '可从事', color: T.success, bg: T.mint },
  fit_with_restriction: { label: '限制从事', color: T.warning, bg: T.peach },
  unfit: { label: '不可从事', color: T.error, bg: T.rose },
}

// ── 在岗状态 → 视觉 ──

export const OH_WORK_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  on_post: { label: '在岗', color: T.success, bg: T.mint },
  off_post: { label: '离岗', color: T.steel, bg: T.gray },
  pre_employment: { label: '岗前', color: '#0075de', bg: T.sky },
  transfer: { label: '转岗', color: T.warning, bg: T.peach },
}

// ── 转岗/离岗类型 → 视觉 ──

export const OH_TRANSFER_TYPE_UI: Record<string, { label: string; color: string; bg: string }> = {
  transfer: { label: '转岗', color: T.warning, bg: T.peach },
  post_employment: { label: '离岗', color: T.steel, bg: T.gray },
}

export const OH_TRANSFER_TYPE_FILTER = [
  { value: '', label: '全部类型' },
  ...Object.entries(OH_TRANSFER_TYPE_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 申请状态（Bitable 7 态原文值）→ 视觉 ──

export const OH_APPLICATION_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  '已通过': { label: '已通过', color: T.success, bg: T.mint },
  '审批中': { label: '审批中', color: '#0075de', bg: T.sky },
  '已拒绝': { label: '已拒绝', color: T.error, bg: T.rose },
  '已取消': { label: '已取消', color: T.steel, bg: T.gray },
  '已终止': { label: '已终止', color: T.steel, bg: T.gray },
  '已撤回': { label: '已撤回', color: T.steel, bg: T.gray },
  '已删除': { label: '已删除', color: T.muted, bg: T.gray },
}

export const OH_APPLICATION_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(OH_APPLICATION_STATUS_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 差异分析状态 → 视觉 ──

export const OH_DIFF_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  none: { label: '未分析', color: T.steel, bg: T.gray },
  parsing: { label: '分析中', color: '#0075de', bg: T.sky },
  analyzed: { label: '已分析', color: T.success, bg: T.mint },
  failed: { label: '分析失败', color: T.error, bg: T.rose },
}

// ── 随访状态 → 视觉 ──

export const OH_FOLLOWUP_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  open: { label: '待处置', color: T.warning, bg: T.peach },
  followed: { label: '已处置待闭环', color: '#0075de', bg: T.sky },
  closed: { label: '已关闭', color: T.steel, bg: T.gray },
  expired: { label: '已逾期', color: T.error, bg: T.rose },
}

export const OH_FOLLOWUP_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(OH_FOLLOWUP_STATUS_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 随访类型 → 视觉 ──

export const OH_FOLLOWUP_TYPE_UI: Record<string, { label: string; color: string; bg: string }> = {
  re_examination: { label: '复查', color: '#0075de', bg: T.sky },
  specialist_referral: { label: '专科转诊', color: T.error, bg: T.rose },
  transfer_post: { label: '调离岗位', color: T.warning, bg: T.peach },
  health_monitor: { label: '健康监护', color: T.success, bg: T.mint },
}

export const OH_FOLLOWUP_TYPE_FILTER = [
  { value: '', label: '全部类型' },
  ...Object.entries(OH_FOLLOWUP_TYPE_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 异常指标类别 → 视觉（pastel 底色轮换）──

export const OH_INDICATOR_CATEGORY_UI: Record<string, { label: string; color: string; bg: string }> = {
  lab: { label: '检验', color: '#0075de', bg: T.sky },
  vision: { label: '视力', color: T.primary, bg: T.lavender },
  hearing: { label: '听力', color: T.warning, bg: T.peach },
  physique: { label: '体格', color: T.success, bg: T.mint },
  other: { label: '其他', color: T.steel, bg: T.gray },
}

export const OH_INDICATOR_CATEGORY_FILTER = [
  { value: '', label: '全部类别' },
  ...Object.entries(OH_INDICATOR_CATEGORY_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 异常程度 → 视觉 ──

export const OH_SEVERITY_UI: Record<string, { label: string; color: string; bg: string }> = {
  mild: { label: '轻度', color: '#0075de', bg: T.sky },
  moderate: { label: '中度', color: T.warning, bg: T.peach },
  severe: { label: '重度', color: T.error, bg: T.rose },
}

// ── 岗位危害填充状态 → 视觉 ──

export const OH_POSITION_FILL_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  filled: { label: '已填', color: T.success, bg: T.mint },
  empty: { label: '未填', color: T.warning, bg: T.peach },
  inferred: { label: 'AI 推断', color: T.primary, bg: T.lavender },
}

export const OH_POSITION_FILL_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(OH_POSITION_FILL_STATUS_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 42 项标准危害因素字典（与后端 OH_HAZARD_FACTORS_STANDARD / Bitable 多选预设一致）──

export const HAZARD_FACTOR_OPTIONS: string[] = [
  '噪声', '氨', '高温', '甲醇', '甲醛', '苯', '甲苯', '甲酸', '乙酸', '磷酸',
  '乙腈', '丙酮', '氰及腈类化合物', '盐酸及氯化氢', '二甲基甲酰胺', '谷物粉尘',
  '锰及其无机化合物', '氮氧化物', '铝尘', '炭黑粉尘', '酸雾或酸酐', '二甲苯',
  '有机粉尘', '压力容器', '矽尘', '硅藻土粉尘', '珍珠岩粉尘', '活性炭粉尘',
  '无机粉尘', '电焊烟尘', '电焊弧光', '二氧化硫', '一氧化碳', '三氯甲烷', '三乙胺',
  '正己烷', '正庚烷', '二氯甲烷', '乙酸乙酯', '硫酸及三氧化硫', '高处作业', '其他粉尘',
]

/** Select options 形态（危害因素筛选/多选） */
export const HAZARD_FACTOR_SELECT_OPTIONS = HAZARD_FACTOR_OPTIONS.map((name) => ({
  value: name,
  label: name,
}))

// ── 是否需体检 → 视觉 ──

export const OH_NEEDS_EXAM_UI: Record<string, { label: string; color: string; bg: string }> = {
  true: { label: '需要体检', color: T.warning, bg: T.peach },
  false: { label: '无需体检', color: T.success, bg: T.mint },
  unknown: { label: '未分析', color: T.steel, bg: T.gray },
}

export const OH_NEEDS_EXAM_FILTER = [
  { value: '', label: '全部' },
  { value: 'true', label: '需要体检' },
  { value: 'false', label: '无需体检' },
]
