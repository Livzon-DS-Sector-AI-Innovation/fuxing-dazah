/**
 * 相关方准入条件审核 常量与语义色映射（DESIGN tokens）
 * 数据源单一：相关方类型/提交状态/培训状态/AI审核状态/审核结论/不符合项分类
 * 的视觉配置与筛选选项都从这里派生。soft tag 浅底深字（statusPill）。
 */
import type { CSSProperties } from 'react'
import { statusPill } from '../shared-styles'

// ── 相关方类型 ──
export const RELATED_PARTY_TYPE_UI: Record<string, { label: string; pill: CSSProperties }> = {
  承包商: { label: '承包商', pill: statusPill('#0075de', '#dcecfa') }, // link-blue + card-tint-sky
  合作类相关方: { label: '合作类相关方', pill: statusPill('#dd5b00', '#ffe8d4') }, // brand-orange + card-tint-peach
  劳务派遣: { label: '劳务派遣', pill: statusPill('#2a9d99', '#e0f4f2') }, // brand-teal + wathet tint
  其他相关方: { label: '其他相关方', pill: statusPill('#8a6d00', '#fef7d6') }, // amber-deep + card-tint-yellow
}

export const RELATED_PARTY_TYPE_FILTER = [
  { value: '', label: '全部类型' },
  ...Object.entries(RELATED_PARTY_TYPE_UI).map(([value, v]) => ({ value, label: v.label })),
]

// ── 提交状态 ──
export const SUBMIT_STATUS_UI: Record<string, { label: string; pill: CSSProperties }> = {
  已完成: { label: '已完成', pill: statusPill('#1aae39', '#d9f3e1') }, // brand-green + card-tint-mint
  进行中: { label: '进行中', pill: statusPill('#dd5b00', '#ffe8d4') }, // brand-orange + card-tint-peach
  未开始: { label: '未开始', pill: statusPill('#e03131', '#fde0ec') }, // semantic-error + card-tint-rose
}

export const SUBMIT_STATUS_FILTER = [
  { value: '', label: '全部提交状态' },
  ...Object.entries(SUBMIT_STATUS_UI).map(([value, v]) => ({ value, label: v.label })),
]

// ── 培训状态 ──
export const TRAINING_STATUS_UI: Record<string, { label: string; pill: CSSProperties }> = {
  已完结: { label: '已完结', pill: statusPill('#1aae39', '#d9f3e1') },
  已培训待补材: { label: '已培训待补材', pill: statusPill('#dd5b00', '#ffe8d4') },
  未培训: { label: '未培训', pill: statusPill('#e03131', '#fde0ec') },
}

// ── AI 审核状态（平台内部状态机 none/processing/completed/failed）──
export const AI_REVIEW_STATUS_UI: Record<string, { label: string; pill: CSSProperties }> = {
  none: { label: '未审核', pill: statusPill('#787671', '#f0eeec') }, // steel + card-tint-gray
  processing: { label: '审核中', pill: statusPill('#0075de', '#dcecfa') },
  completed: { label: '已审核', pill: statusPill('#1aae39', '#d9f3e1') },
  failed: { label: '审核失败', pill: statusPill('#e03131', '#fde0ec') },
}

export const AI_REVIEW_STATUS_FILTER = [
  { value: '', label: '全部审核状态' },
  { value: 'none', label: '未审核' },
  { value: 'processing', label: '审核中' },
  { value: 'completed', label: '已审核' },
  { value: 'failed', label: '审核失败' },
]

// ── AI 审核总体结论（与 Bitable 单选选项一致）──
export const ADMISSION_CONCLUSION_UI: Record<string, CSSProperties> = {
  审核通过: statusPill('#1aae39', '#d9f3e1'),
  需补充完善: statusPill('#dd5b00', '#ffe8d4'),
  审核不通过: statusPill('#e03131', '#fde0ec'),
}

export const ADMISSION_CONCLUSION_FILTER = [
  { value: '', label: '全部结论' },
  { value: '审核通过', label: '审核通过' },
  { value: '需补充完善', label: '需补充完善' },
  { value: '审核不通过', label: '审核不通过' },
]

// ── 不符合原因分类（与 Bitable 多选选项一致：带「安全管理协议-」附件前缀）──
// 旧 key（无前缀）保留兼容历史数据；新审核输出统一使用带前缀 key。
export const DEFECT_CATEGORY_UI: Record<string, { label: string; pill: CSSProperties }> = {
  '安全管理协议-A基础信息类': { label: '安全管理协议-A基础信息类', pill: statusPill('#0075de', '#dcecfa') },
  '安全管理协议-B有效期类': { label: '安全管理协议-B有效期类', pill: statusPill('#dd5b00', '#ffe8d4') },
  '安全管理协议-C签章类': { label: '安全管理协议-C签章类', pill: statusPill('#e03131', '#fde0ec') },
  '安全管理协议-D骑缝章类': { label: '安全管理协议-D骑缝章类', pill: statusPill('#5645d4', '#e6e0f5') },
  // 兼容历史数据（无前缀旧值）
  A基础信息类: { label: 'A基础信息类', pill: statusPill('#0075de', '#dcecfa') },
  B有效期类: { label: 'B有效期类', pill: statusPill('#dd5b00', '#ffe8d4') },
  C签章类: { label: 'C签章类', pill: statusPill('#e03131', '#fde0ec') },
  D骑缝章类: { label: 'D骑缝章类', pill: statusPill('#5645d4', '#e6e0f5') },
}
