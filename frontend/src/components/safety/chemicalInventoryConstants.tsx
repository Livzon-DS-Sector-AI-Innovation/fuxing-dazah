// 危化品库存管理（Chemical Inventory）— UI 常量 & 视觉映射
// 配色取自 shared-styles / emergencyDrillConstants 的 T、UI、CARD_STYLE
// 后端权威清单：dazah-backend/app/modules/safety/schemas/chemical_inventory.py

import { T } from './shared-styles'
import { UI, CARD_STYLE } from './emergencyDrillConstants'

export { T, UI, CARD_STYLE }

// ── 部门（英文枚举 → 中文标签）──
export const CHEMICAL_DEPARTMENT_LABELS: Record<string, string> = {
  warehouse: '仓储部',
  extraction_1: '提炼一部',
  extraction_2: '提炼二期',
  extraction_2b: '提炼二部',
  fermentation_1: '发酵一部',
  fermentation_2: '发酵二部',
  strain: '菌种中心',
  qc: 'QC',
  env: '环保',
  purification: '精制',
  semi_synth: '提炼半合成工程中心',
  tech_refine: '提炼技术精进中心',
  other: '其他',
}

export const CHEMICAL_DEPARTMENT_FILTER = [
  { value: '', label: '全部部门' },
  ...Object.entries(CHEMICAL_DEPARTMENT_LABELS).map(([value, label]) => ({ value, label })),
]

// ── 单位 ──
export const CHEMICAL_UNIT_LABELS: Record<string, string> = {
  kg: 'kg', g: 'g', T: 'T', L: 'L', ml: 'ml', bottle: '瓶',
}

// ── 危险性 ──
export const HAZARD_CLASS_LABELS: Record<string, string> = {
  flammable: '易燃',
  explosive: '易爆',
  precursor_drug: '易制毒',
  precursor_explosive: '易制爆',
  corrosive: '腐蚀',
  toxic: '毒性',
  oxidizer: '氧化剂',
  irritant: '刺激性',
}

// ── 风险标记（2 值）→ 视觉 ──
export const RISK_FLAG_UI: Record<string, { label: string; color: string; bg: string }> = {
  normal: { label: '正常', color: T.success, bg: T.mint },
  warn: { label: '预警', color: T.error, bg: T.rose },
}

// ── 风险说明（正常 + 8 预警类型）→ 视觉 ──
export const RISK_NOTE_UI: Record<string, { label: string; color: string; bg: string }> = {
  normal: { label: '正常', color: T.success, bg: T.mint },
  over_limit: { label: '超量', color: T.error, bg: T.rose },
  near_limit: { label: '临限', color: T.warning, bg: T.peach },
  high_ratio: { label: '高占比', color: '#793400', bg: T.yellow },
  incompatible_storage: { label: '禁忌混存', color: T.error, bg: T.rose },
  unclassified: { label: '未分类', color: T.warning, bg: T.yellow },
  unit_anomaly: { label: '单位异常', color: T.warning, bg: T.yellow },
  special_storage: { label: '专库违规', color: T.warning, bg: T.peach },
}

// ── 顶部 KPI 卡片定义 ──
export const CHEMICAL_KPI_ITEMS: Array<{
  label: string
  field: keyof import('@/types/safety').ChemicalInventoryStats
  bg: string
  valueColor: string
  caption: string
}> = [
  { label: '化学品总数', field: 'total_records', bg: T.lavender, valueColor: T.primary, caption: '当前台账行数' },
  { label: '预警', field: 'warn_count', bg: T.rose, valueColor: T.error, caption: '风险标记=预警' },
  { label: '超量', field: 'over_limit', bg: T.rose, valueColor: T.error, caption: '总量超过上限' },
  { label: '正常', field: 'normal_count', bg: T.mint, valueColor: T.success, caption: '风险标记=正常' },
]
