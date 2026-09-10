// MSDS 智能提取入库 — UI 常量 & 视觉映射
// 配色取自 DESIGN.md tokens，参考 emergencyDrillConstants 模式

import { T, UI, CARD_STYLE } from './emergencyDrillConstants'

export { T, UI, CARD_STYLE }

// ── 解析状态 → 视觉 ──

export const PARSE_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: '待解析', color: T.steel, bg: T.gray },
  parsed: { label: '已解析', color: '#1aae39', bg: T.mint },
  failed: { label: '解析失败', color: T.error, bg: T.rose },
}

export const PARSE_STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(PARSE_STATUS_UI).map(([value, ui]) => ({ value, label: ui.label })),
]

// ── 复核状态 → 视觉 ──

export const REVIEW_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: '待复核', color: T.steel, bg: T.gray },
  approved: { label: '已复核', color: '#1aae39', bg: T.mint },
  rejected: { label: '已驳回', color: T.error, bg: T.rose },
}

// ── 归档状态 → 视觉 ──

export const ARCHIVE_STATUS_UI: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: '未归档', color: T.steel, bg: T.gray },
  archived: { label: '已归档', color: '#0075de', bg: T.sky },
}

// ── MSDS 详情展示字段分组（28 字段）──
export const MSDS_DETAIL_GROUPS: { label: string; fields: { label: string; key: string }[] }[] = [
  {
    label: '基础标识',
    fields: [
      { label: '物质名称', key: 'name' },
      { label: 'CAS号', key: 'cas_no' },
      { label: '分子式', key: 'molecular_formula' },
      { label: 'UN编号', key: 'un_no' },
    ],
  },
  {
    label: '危险性概述',
    fields: [
      { label: '危险性说明', key: 'hazard_statement' },
      { label: '标签要素', key: 'label_elements' },
    ],
  },
  {
    label: '理化特性',
    fields: [
      { label: '外观与现状', key: 'appearance' },
      { label: '溶解性', key: 'solubility' },
      { label: '熔点', key: 'melting_point' },
      { label: '沸点', key: 'boiling_point' },
      { label: '闪点', key: 'flash_point' },
      { label: '相对密度', key: 'relative_density' },
      { label: '爆炸上限(%)', key: 'explosion_upper_limit' },
      { label: '爆炸下限(%)', key: 'explosion_lower_limit' },
      { label: '自燃温度', key: 'autoignition_temperature' },
      { label: '分解温度', key: 'decomposition_temperature' },
    ],
  },
  {
    label: '职业接触限值',
    fields: [
      { label: 'PC-TWA', key: 'pc_twa' },
      { label: 'PC-STEL', key: 'pc_stel' },
      { label: 'MAC', key: 'mac' },
    ],
  },
  {
    label: '健康与环境危害',
    fields: [
      { label: '健康危害', key: 'health_hazard' },
      { label: '环境危害', key: 'environmental_hazard' },
    ],
  },
  {
    label: '应急响应',
    fields: [
      { label: '急救措施', key: 'first_aid' },
      { label: '消防措施', key: 'fire_fighting' },
      { label: '泄漏应急处理', key: 'leakage_response' },
      { label: '废弃处置', key: 'waste_disposal' },
    ],
  },
  {
    label: '防护与控制',
    fields: [
      { label: '接触控制与个体防护', key: 'exposure_controls' },
      { label: '操作处置与储存注意事项', key: 'handling_storage' },
      { label: '稳定性和反应性', key: 'stability_reactivity' },
    ],
  },
]
